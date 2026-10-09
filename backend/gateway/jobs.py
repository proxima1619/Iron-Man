"""Bounded evaluation processes with deadlines and guarded result publication.

Only the server process accesses SQLite or the virtual equipment. Spawned workers
receive a request/snapshot and return a report. Termination cannot apply commands.
"""
import logging
import multiprocessing
import threading
import time
import uuid
from dataclasses import dataclass, field
from fastapi import HTTPException
from backend.gateway.evaluation import failure_report, process_worker

logger = logging.getLogger(__name__)

@dataclass
class Job:
    context: dict
    process: object
    output: object
    deadline: float
    cancelled: threading.Event = field(default_factory=threading.Event)
    watcher: threading.Thread | None = None

class EvaluationRunner:
    def __init__(self, gateway, capacity=2, timeout_s=90, worker_target=None):
        if not 1 <= capacity <= 4 or not 0 < timeout_s <= 300:
            raise ValueError('Evaluation workers must be 1..4 and timeout must be >0..300 seconds')
        self.gateway = gateway
        self.capacity = capacity
        self.timeout_s = timeout_s
        self.worker_target = worker_target or process_worker
        self.context = multiprocessing.get_context('spawn')
        self.jobs = {}
        self.closed = False

    def submit(self, request_id):
        with self.gateway.lock:
            if self.closed:
                raise HTTPException(503, '서버가 종료 중입니다.')
            if self.gateway.get(request_id)['status'] == 'evaluating':
                raise HTTPException(409, '이 요청은 이미 평가 중입니다.')
            if len(self.jobs) >= self.capacity:
                raise HTTPException(429, '평가 작업이 모두 사용 중입니다. 잠시 후 다시 시도하세요.', headers={'Retry-After': '1'})
            now = time.time()
            task = {'id': str(uuid.uuid4()), 'revision': 0, 'status': 'running',
                    'started_at': now, 'deadline_at': now + self.timeout_s, 'finished_at': None}
            row, context = self.gateway._prepare_evaluation(request_id, task)
            reader = writer = process = None
            try:
                reader, writer = self.context.Pipe(duplex=False)
                process = self.context.Process(target=self.worker_target, args=(context, writer), daemon=True)
                job = Job(context, process, reader, time.monotonic() + self.timeout_s)
                process.start()
                writer.close()
                self.jobs[task['id']] = job
                job.watcher = threading.Thread(target=self._watch, args=(job,), daemon=True,
                                                name=f'evaluation-{task["id"]}')
                job.watcher.start()
            except Exception:
                if writer:
                    writer.close()
                if reader:
                    reader.close()
                self.jobs.pop(task['id'], None)
                if process and process.pid:
                    self._stop(process)
                    process.close()
                self.gateway._finish_evaluation(context, failure_report(context, 'WORKER_FAILURE',
                    '평가 프로세스를 시작하지 못했습니다.'), 'failed')
                raise HTTPException(503, '평가 프로세스를 시작하지 못했습니다.')
            return row  # Captured running record, even if the worker finishes immediately.

    @staticmethod
    def _stop(process):
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)

    def _watch(self, job):
        try:
            while not job.cancelled.is_set():
                remaining = job.deadline - time.monotonic()
                if remaining <= 0:
                    self._stop(job.process)
                    self.gateway._finish_evaluation(job.context, failure_report(job.context,
                        'EVALUATION_TIMEOUT', '평가 제한 시간을 초과했습니다. 실행을 보류합니다.'), 'timed_out')
                    return
                if job.output.poll(min(0.1, remaining)):
                    report = job.output.recv()
                    self.gateway._finish_evaluation(job.context, report)
                    return
                if not job.process.is_alive():
                    raise RuntimeError('Evaluation worker exited without a report')
        except Exception:
            try:
                self.gateway._finish_evaluation(job.context, failure_report(job.context,
                    'WORKER_FAILURE', '평가 프로세스 결과를 확인하지 못했습니다. 실행을 보류합니다.'), 'failed')
            except Exception:
                # A persistent DB error leaves durable evaluating state for restart recovery.
                logger.exception('Unable to persist evaluation failure')
        finally:
            self._stop(job.process)
            job.output.close()
            job.process.close()
            with self.gateway.lock:
                self.jobs.pop(job.context['task_id'], None)

    def cancel(self, request_id):
        with self.gateway.lock:
            row = self.gateway.get(request_id)
            task = row.get('evaluation')
            job = self.jobs.get(task['id']) if task else None
            if row['status'] != 'evaluating' or not job:
                raise HTTPException(409, '취소할 평가 작업이 없습니다.')
            result = self.gateway._finish_evaluation(job.context, failure_report(job.context,
                'EVALUATION_CANCELLED', '사용자가 평가를 취소했습니다. 다시 검증할 수 있습니다.'), 'cancelled')
            job.cancelled.set()
        # The watcher reaps the process; do not join while holding the gateway lock.
        job.watcher.join(timeout=3)
        return result

    def close(self):
        with self.gateway.lock:
            if self.closed:
                return
            self.closed = True
            jobs = list(self.jobs.values())
            for job in jobs:
                try:
                    self.gateway._finish_evaluation(job.context, failure_report(job.context,
                        'EVALUATION_CANCELLED', '서버 종료로 평가를 중단했습니다. 다시 검증하세요.'), 'cancelled')
                except Exception:
                    logger.exception("Unable to persist evaluation shutdown")
                finally:
                    job.cancelled.set()
        for job in jobs:
            job.watcher.join()  # Watcher terminates/reaps its child before DB is closed.
