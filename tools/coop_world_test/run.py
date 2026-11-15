# Offline checks (lupa, LuaJIT) of coop_pulse_anomaly, coop_trader_restock, coop_time (the master underground),
# coop_surge_sound, coop_crows, coop_squads (offline health) and coop_zone_events.now() on stub games sharing the
# server's facts. python run.py
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
bad = 0
for t in ('test_pulse.py', 'test_trader.py', 'test_weather.py', 'test_misc.py'):
    print('==', t)
    bad += subprocess.call([sys.executable, os.path.join(here, t)])
print('all passed' if bad == 0 else '%d file(s) failed' % bad)
sys.exit(1 if bad else 0)
