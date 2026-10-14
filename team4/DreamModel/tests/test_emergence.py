"""The empty-to-formed requirement, checked independently of event animation."""
from dataclasses import replace
import unittest
import numpy as np
import cv2
from team4.DreamModel.config import RenderConfig
from team4.DreamModel.archive.developmental_pipeline import prepare
from team4.DreamModel.archive.emergence_renderer import EmergenceRenderer
from team4.DreamModel.archive.developmental_world import DevelopmentalWorld


class EmergenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        cls.bundle,cls.plans,cls.memories,cls.events,_,_=prepare(replace(RenderConfig(),width=320,height=180))
        cls.renderer=EmergenceRenderer(cls.bundle,cls.plans,320,180)

    def simulation(self,**flags):
        w=DevelopmentalWorld(self.plans,memories=self.memories,events=self.events,**flags)
        frames={};stats={}
        for frame in range(601):
            t=frame/30;w.step(t,1/30,.5+.2*np.sin(t),.1)
            if frame in (0,240,420,600):
                frames[t]=self.renderer.render(w).copy()
                stats[t]=self.renderer.stats.copy()
        return frames,stats

    def test_no_scene_or_object_is_present_in_initial_frame(self):
        frames,stats=self.simulation()
        self.assertEqual(sum(stats[0.]['surface_area_pixels'].values()),0)
        self.assertEqual(np.ptp(frames[0.],axis=(0,1)).max(),0)
        # Both kinds of matter develop spatial extent, not just brightness.
        for kind in ('space','journal','pool','figure'):
            self.assertGreater(stats[20.]['surface_area_pixels'][kind],stats[8.]['surface_area_pixels'][kind]+1)
        coverage=[np.count_nonzero(np.max(abs(frames[t].astype(float)-frames[0.]),axis=2)>15) for t in (8.,14.,20.)]
        self.assertTrue(coverage[0]<coverage[1]<coverage[2])

    def test_each_condition_changes_the_formation_itself(self):
        reference,stats=self.simulation()
        for flag in ('story','emotion','sound'):
            changed,measure=self.simulation(**{flag:False})
            self.assertGreater(np.mean(abs(reference[20.].astype(float)-changed[20.])),.15)
            self.assertNotEqual(stats[20.]['surface_area_pixels'],measure[20.]['surface_area_pixels'])

    def test_spatial_parent_graph_and_foreground_support_are_available(self):
        r=self.renderer
        for kind in ('space','journal','pool','figure'):
            patches=[p for p in r.patches if p.kind==kind]
            self.assertTrue(any(p.parent!=p.index for p in patches))
            self.assertTrue(all(len(p.contour)>=3 for p in patches))
        self.assertTrue(all(id(p) in r.support for p in r.patches if p.kind!='space'))


if __name__=='__main__':unittest.main()
