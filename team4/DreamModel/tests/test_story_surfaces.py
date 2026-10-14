"""Causal checks of the active story renderer; pixels are not visual acceptance."""
from dataclasses import replace
from pathlib import Path
import unittest
import cv2
import numpy as np
from team4.DreamModel.config import REPO_ROOT,RenderConfig
from team4.DreamModel.developmental_pipeline import prepare,render
from team4.DreamModel.developmental_world import DevelopmentalWorld
from team4.DreamModel.developmental_renderer import DevelopmentalRenderer
from team4.DreamModel.story_events import StoryEvents
from team4.DreamModel.audience import AudienceAtmosphere


class StorySurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        cls.config=replace(RenderConfig(),width=320,height=180,smoke=True,scene_count=2,
            preview_start_seconds=65,preview_seconds=20,transition_seconds=20)
        cls.bundle,cls.plans,cls.memories,cls.events,_,_=prepare(cls.config)

    def world(self,**flags):
        return DevelopmentalWorld(self.plans,memories=self.memories,events=self.events,**flags)

    def advance(self,w,end):
        for frame in range(round(end*30)+1):
            t=frame/30
            w.step(t,1/30,.45+.25*np.sin(t*.3),.08+.04*np.sin(t*.7))
        return w

    def test_explicit_laws_are_loaded_and_only_supported_ones_are_compiled(self):
        self.assertEqual(len(self.bundle.scenes[0].physics_laws),5)
        self.assertEqual(len(self.bundle.scenes[1].physics_laws),7)
        self.assertEqual(len(self.events.events),12)
        self.assertEqual(len(self.events.unsupported),8)
        reduced=replace(self.bundle.scenes[0],physics_laws=())
        no_laws=StoryEvents((reduced,*self.bundle.scenes[1:]))
        self.assertEqual(no_laws.progress('page_turn',72),0)
        self.assertFalse(no_laws.enabled('recede'))

    def test_late_scene_two_events_are_not_compressed_into_preview(self):
        e=self.events
        self.assertEqual(e.progress('erase_before_water',85),0)
        self.assertEqual(e.progress('hand_pool',85),0)
        self.assertEqual(e.progress('page_turn',65),0)
        self.assertGreater(e.progress('page_turn',71),.5)
        self.assertEqual(e.progress('erase',74),1)
        self.assertGreater(e.progress('erase_before_water',132),.8)

    def test_memory_transfer_keeps_real_geometry_and_influences_next_growth(self):
        w=self.advance(self.world(),65)
        np.testing.assert_array_equal(w.inheritance['surface_before'],w.inheritance['surface_after'])
        self.assertGreater(w.memory_field.sum(),1)
        self.assertTrue(any(len(p.lineage)>1 for p in w.search.champions.values()))
        r=DevelopmentalRenderer(320,180,self.memories)
        r.render(w)
        reset=self.advance(self.world(memory=False),65)
        self.assertGreater(np.linalg.norm(w.page_points-reset.page_points),.01)
        w2=self.advance(self.world(memory=False),75)
        w1=self.advance(self.world(),75)
        self.assertGreater(w1.memory_field.sum(),1.)
        self.assertEqual(w2.memory_field.sum(),0.)
        a=r.render(w1)
        b=DevelopmentalRenderer(320,180,self.memories).render(w2)
        self.assertGreater(np.abs(a.astype(float)-b).mean(),.05)

    def test_archive_has_real_descriptor_cells_and_partner_dependent_fitness(self):
        w=self.advance(self.world(),20)
        self.assertTrue(all(len(v)>1 for v in w.search.archives.values()))
        s=w.search.champions['space'];o=w.search.champions['journal']
        original=w.search.joint_quality(s,o,0,1.)
        other=replace(s,genes=np.clip(1-s.genes,0,1))
        self.assertNotAlmostEqual(original,w.search.joint_quality(other,o,0,1.))
        self.assertTrue(any(e['changed_topology'] for e in w.search.events))

    def test_story_emotion_and_sound_change_actual_pixels_and_structure(self):
        frames=[];worlds=[]
        for flags in ({},{'story':False},{'emotion':False},{'sound':False}):
            w=self.advance(self.world(**flags),71)
            frames.append(DevelopmentalRenderer(320,180,self.memories).render(w))
            worlds.append(w)
        for i in range(1,4):
            self.assertGreater(np.abs(frames[0].astype(float)-frames[i]).mean(),.08)
            self.assertNotEqual(worlds[0].snapshot(),worlds[i].snapshot())
        self.assertEqual(worlds[1].channels['page_turn'],0)
        self.assertGreater(worlds[0].channels['page_turn'],.5)
        self.assertTrue(np.all(worlds[3].audio==0))

    def test_actual_asset_statistics_affect_the_evolving_genotype(self):
        with_assets=self.world()
        without=DevelopmentalWorld(self.plans,events=self.events)
        self.assertFalse(np.array_equal(with_assets.genes['journal'],without.genes['journal']))
        self.assertFalse(np.array_equal(with_assets.genes['space'],without.genes['space']))

    def test_audience_parameters_influence_search_without_claiming_measurements(self):
        base=self.advance(self.world(),20)
        other=self.advance(DevelopmentalWorld(self.plans,atmosphere=AudienceAtmosphere(.9,.8,.2,'synthetic test'),
            memories=self.memories,events=self.events),20)
        self.assertFalse(np.array_equal(base.genes['figure'],other.genes['figure']))

    def test_active_pipeline_rejects_final_and_time_compression(self):
        with self.assertRaisesRegex(ValueError,'preview only'):render(RenderConfig())
        with self.assertRaisesRegex(ValueError,'75-second'):render(replace(self.config,scene_seconds=10,transition_seconds=5))


if __name__=='__main__':unittest.main()
