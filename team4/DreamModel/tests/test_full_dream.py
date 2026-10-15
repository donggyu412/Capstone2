"""Distinct engines, complete story scope, exact continuity at encoding splits."""
from dataclasses import replace
import pickle,unittest
import numpy as np
from team4.DreamModel.config import RenderConfig
from team4.DreamModel.runtime.dream_pipeline import prepare
from team4.DreamModel.runtime.dream_world import DreamWorld
from team4.DreamModel.runtime.dream_surfaces import DreamSurfaces


class FullDreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=replace(RenderConfig(),width=160,height=90)
        cls.bundle,cls.plans,cls.audio,cls.templates,_,_,_,cls.score,_=prepare(cls.config)

    def world(self):
        w=DreamWorld(self.bundle.scenes,self.plans,self.templates,101,self.config.audience)
        w.score=self.score
        return w

    def test_every_supplied_law_has_an_explicit_interpretation(self):
        self.assertEqual(len(self.score.events),20)
        self.assertEqual(self.score.unsupported,[])
        self.assertEqual({e['scene'] for e in self.score.events.values()},{1,2,3,4})

    def test_empty_birth_and_distinct_engines(self):
        w=self.world();r=DreamSurfaces(self.templates,160,90,self.score)
        w.step(0,1/30,.5,.1);frame=r.render(w)
        self.assertEqual(np.ptp(frame,axis=(0,1)).max(),0)
        for f in range(1,901):w.step(f/30,1/30,.5,.1)
        field=w.states[0]['space']
        self.assertGreater(field.material.mean(),.45)
        self.assertGreater(np.ptp(field.u.mean(axis=1)),.01)
        self.assertGreater(field.updates,20)
        self.assertTrue(any(np.mean(v)>.6 for v in w.states[0]['objects'].values()))
        self.assertTrue(any(e['parents'] for e in w.evolution.events))
        self.assertGreater(len({e['nodes'] for e in w.evolution.events}),1)
        for p in w.evolution.champions.values():
            self.assertEqual(len(p.links),len(p.control)-1)
            self.assertTrue(all(0<=parent<child for child,parent in p.links))

    def test_checkpoint_preserves_pixels_at_boundary(self):
        w=self.world()
        for f in range(2250):w.step(f/30,1/30,.4,.05)
        resumed=pickle.loads(pickle.dumps(w))
        a=DreamSurfaces(self.templates,160,90,self.score)
        b=DreamSurfaces(resumed.templates,160,90,resumed.score)
        for f in range(2250,2253):
            w.step(f/30,1/30,.4,.05);resumed.step(f/30,1/30,.4,.05)
            self.assertTrue(np.array_equal(a.render(w),b.render(resumed)))
        self.assertGreater(w.inheritance[0]['initial_trace_mass'],0)
        self.assertTrue(w.inheritance[0]['structural_donors'])


if __name__=='__main__':unittest.main()
