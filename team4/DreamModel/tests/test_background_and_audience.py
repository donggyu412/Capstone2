"""Distinct algorithms, real cross-influence and aggregate-input boundaries."""
from dataclasses import replace
import unittest
import numpy as np
from team4.DreamModel.runtime.audience import AudienceAtmosphere
from team4.DreamModel.archive.background_evolution import BackgroundEvolution
from team4.DreamModel.archive.evolving_brush import EvolvingBrush
from team4.DreamModel.archive.geometric_evolution import Evolution
from team4.DreamModel.runtime.input_loader import load_inputs
from team4.DreamModel.main import parse_config
from team4.DreamModel.archive.memory_grammar import MemoryField
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary
from team4.DreamModel.tests import test_input_loader as fixtures


class BackgroundAudienceTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.InputLoaderTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fields=[MemoryField(s,SemanticLibrary()) for s in load_inputs(fixture.root).scenes[:2]]

    def test_object_population_excludes_background_graphs(self):
        coupling=EvolvingBrush(self.fields,101)
        for field in coupling.engine.memories:
            self.assertTrue(field.motifs)
            self.assertTrue(all(m.family!='space' for m in field.motifs))
        self.assertIsInstance(coupling.background,BackgroundEvolution)
        self.assertIs(coupling.engine.spatial_field,coupling.background.field)

    def test_background_search_and_memory_survive_scene_change(self):
        e=BackgroundEvolution(self.fields,101);before=e.programs.copy()
        for _ in range(400):e.step(1/30,.4,np.zeros((54,96),dtype='float32'))
        self.assertEqual(len(e.events),2)
        self.assertFalse(np.array_equal(before,e.programs))
        before=e.field.copy();programs=e.programs.copy()
        e.enter_scene(1)
        np.testing.assert_array_equal(e.field,before)
        np.testing.assert_array_equal(e.programs,programs)

    def test_objects_change_background_and_background_changes_selection(self):
        a=BackgroundEvolution(self.fields,101);b=BackgroundEvolution(self.fields,101)
        for _ in range(60):
            a.step(1/30,.4,np.zeros((54,96),dtype='float32'))
            b.step(1/30,.4,np.ones((54,96),dtype='float32'))
        self.assertGreater(float(b.field.mean()),float(a.field.mean()))
        values=[]
        for support in (0.,1.):
            e=Evolution(self.fields,101);e.enter_scene(0)
            e.spatial_field=np.full((54,96),support,dtype='float32')
            o=e.birth(self.fields[0].motifs[-1]);e.select();values.append(o.fitness)
        self.assertGreater(values[1],values[0])

    def test_audience_changes_both_processes_without_replacing_scene_emotion(self):
        outputs=[]
        for atmosphere in (AudienceAtmosphere(),AudienceAtmosphere(.9,.9,.1,'test aggregate')):
            e=EvolvingBrush(self.fields,101,atmosphere)
            for frame in range(750):e.step(frame/30/75,1/30,.6,.15)
            outputs.append((e.background.field.copy(),e.engine.events))
            self.assertEqual(e.engine.memory.scene.emotion_intensity,.8)
        self.assertFalse(np.array_equal(outputs[0][0],outputs[1][0]))
        self.assertNotEqual(outputs[0][1],outputs[1][1])

    def test_aggregate_controls_are_validated_and_provenance_is_explicit(self):
        for value in (-.1,1.1,float('nan')):
            with self.assertRaises(ValueError):AudienceAtmosphere(arousal=value)
        cfg,_=parse_config(['--preview','--audience-arousal','.7','--audience-tension','.6',
            '--audience-coherence','.8','--audience-source','supplied group summary'])
        self.assertEqual(cfg.audience,AudienceAtmosphere(.7,.6,.8,'supplied group summary'))
        self.assertIn('no measured',AudienceAtmosphere().source)


if __name__=='__main__':unittest.main()
