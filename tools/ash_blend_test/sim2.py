import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blend_sim as B
orig = B.Env.set_weather
def sw(self, w, forced):
    if w is not self.W: forced = False
    orig(self, w, forced)
B.Env.set_weather = sw
worst=[]
for seed in range(300):
    l, rr, ev, tf = B.run(seed)
    worst.append((round(l,1), seed, round(rr,1), ev))
worst.sort(reverse=True)
for w in worst[:6]: print(w)
print(sum(1 for w in worst if w[3]))
