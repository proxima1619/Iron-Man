// Iron-Man protocol wrapper; the process equations are the unmodified NIST core.
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>
#include "vendor/teprob.h"

static void row(double seconds, double* state, double* inputs) {
    double outputs[NY];
    get_curr_xmeas(outputs);
    std::cout << seconds << ',' << get_curr_shutdown();
    for (int i = 0; i < NU; ++i) std::cout << ',' << inputs[i];
    for (int i = 0; i < NY; ++i) std::cout << ',' << outputs[i];
    for (int i = 0; i < NX; ++i) std::cout << ',' << state[i];
    std::cout << '\n';
}

int main(int argc, char** argv) {
    try {
        if (argc != 5) throw std::runtime_error("Expected XMV index, value, horizon seconds, sample seconds");
        int index = std::stoi(argv[1]), horizon = std::stoi(argv[3]), sample = std::stoi(argv[4]);
        double value = std::stod(argv[2]);
        if ((index != 10 && index != 11) || !std::isfinite(value) || value < 0 || value > 100
            || horizon < 1 || horizon > 1800 || sample < 1 || sample > 60 || horizon % sample)
            throw std::runtime_error("Unsupported configuration");
        const integer count = NX;
        double time = 0, state[NX] = {}, derivative[NX] = {}, inputs[NU] = {};
        int disturbances[NIDV] = {};
        set_curr_idv(disturbances);
        teinit(&count, &time, state, derivative);
        get_curr_xmv(inputs);
        std::cout << std::setprecision(17) << "time_s,shutdown";
        for (int i = 1; i <= NU; ++i) std::cout << ",XMV" << i;
        for (int i = 1; i <= NY; ++i) std::cout << ",XMEAS" << i;
        for (int i = 1; i <= NX; ++i) std::cout << ",STATE" << i;
        std::cout << '\n';
        row(0, state, inputs); // Both branches expose the identical pre-command state.
        inputs[index - 1] = value;
        set_curr_xmv(inputs);
        tefunc(&count, &time, state, derivative);
        // TE core is stateful (noise/delays): one evaluation per fixed step, no RK stages.
        for (int step = 1; step <= horizon * 10; ++step) {
            for (int i = 0; i < NX; ++i) {
                state[i] += derivative[i] * (0.1 / 3600.0);
                if (!std::isfinite(state[i])) throw std::runtime_error("Nonfinite internal state");
            }
            time = step / 36000.0; // Core time and derivatives are in hours.
            tefunc(&count, &time, state, derivative);
            if (get_curr_shutdown() != 0) {
                row(step / 10.0, state, inputs);
                std::cerr << "TE shutdown code " << get_curr_shutdown() << ": " << get_shutdown_msg() << '\n';
                return 2;
            }
            if (step % (sample * 10) == 0) row(step / 10.0, state, inputs);
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
