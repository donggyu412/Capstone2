"""Causal and structural tests for the active geometric engine."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
from team4.DreamModel.input_loader import load_inputs
from team4.DreamModel.memory_grammar import MemoryField
from team4.DreamModel.semantic_conditioning import SemanticLibrary
from team4.DreamModel.geometric_evolution import Evolution, GeometricRenderer
from team4.DreamModel.geometric_pipeline import render
from team4.DreamModel.config import RenderConfig
from team4.DreamModel.tests import test_input_loader as fixtures


class GeometricTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.InputLoaderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        scenes = load_inputs(self.fixture.root).scenes
        self.fields = [MemoryField(replace(s, story=s.objects[0].name + ' ' * 15 +
                        '\n\n' + s.objects[1].name), SemanticLibrary()) for s in scenes]

    def engine(self, **kw):
        e = Evolution(self.fields, **kw)
        e.enter_scene(0)
        return e

    def mature(self, e):
        o = e.birth(self.fields[0].motifs[-1])
        for _ in range(len(o.motif.path) + 1): e.grow(o)
        return o

    def test_memory_contains_features_but_no_renderable_source_image(self):
        m = self.fields[0]
        self.assertEqual(m.region_energy.shape, (5,8))
        self.assertFalse(m.report()['renderer_receives_source_images'])
        self.assertFalse(any(isinstance(v,np.ndarray) and v.ndim==3 for v in vars(m).values()))

    def test_birth_is_sparse_then_topology_grows_and_closes(self):
        e = self.engine();o=e.birth(self.fields[0].motifs[-1])
        self.assertEqual(len(o.controlPoints),2)
        before=len(o.connections)
        for _ in range(len(o.motif.path)+1):e.grow(o)
        self.assertGreater(len(o.connections),before)
        self.assertTrue(o.closed)
        self.assertTrue(o.faces)

    def test_mutation_changes_connected_graph_not_only_render_parameter(self):
        e=self.engine();o=self.mature(e);n=len(o.rest);d=o.descriptor().copy()
        e.mutate(o,'branch')
        self.assertEqual(len(o.rest),n+2)
        self.assertTrue(any(n in edge for edge in o.connections))
        self.assertFalse(np.array_equal(d,o.descriptor()))

    def test_recombination_copies_parent_nodes_and_lineage(self):
        e=self.engine();a=self.mature(e);b=self.mature(e);n=len(a.rest)
        self.assertTrue(e.combine(a,b,True))
        self.assertGreater(len(a.rest),n)
        self.assertIn(b.uid,a.lineage)
        self.assertTrue(b.dying)
        self.assertTrue(any(x<n<=y for x,y in a.connections))

    def test_inheritance_preserves_actual_geometry_not_just_alpha(self):
        e=self.engine();o=self.mature(e);before=o.rest.copy();o.energy=.9
        e.enter_scene(1)
        self.assertTrue(o.inherited)
        np.testing.assert_array_equal(o.rest,before)
        self.assertEqual(e.transfers[0]['survivors'][0]['id'],o.uid)

    def test_selection_penalizes_lost_memory_and_duplicate_family(self):
        e=self.engine();a=self.mature(e);b=self.mature(e)
        b.rest += 4
        e.select()
        self.assertGreater(a.fitness,b.fitness)
        self.assertGreater(a.memoryAffinity,b.memoryAffinity)
        self.assertEqual(a.diversity,.5)

    def test_identical_topology_is_not_novel(self):
        e=self.engine();a=self.mature(e);b=self.mature(e)
        b.rest=a.rest.copy();b.connections=list(a.connections);b.scale=a.scale.copy()
        b.mutations=a.mutations;b.lineage=(b.uid,)
        e.select()
        self.assertAlmostEqual(a.novelty,0)

    def test_extinction_removes_organism_after_continuous_decay(self):
        e=self.engine();o=self.mature(e);o.opacity=1.;e.kill(o,'test')
        e.step(.5,1/30);self.assertGreater(o.opacity,0);self.assertLess(o.opacity,1)
        for _ in range(90):e.step(.5,1/30)
        self.assertNotIn(o,e.population)

    def signature(self, **kw):
        e=self.engine(**kw);r=GeometricRenderer(160,90);hashes=[]
        for t in range(120):
            e.step(t/119,1/30,.7+.2*np.sin(t*.13),.3)
            if t%10==0:hashes.append(r.render(e).tobytes())
        return b''.join(hashes),e

    def test_determinism_and_seed_variation(self):
        a,_=self.signature();b,_=self.signature();c,_=self.signature(seed=202)
        self.assertEqual(a,b);self.assertNotEqual(a,c)

    def test_each_condition_changes_visible_output(self):
        normal,_=self.signature()
        for condition in ('story','emotion','sound'):
            with self.subTest(condition=condition):
                other,e=self.signature(**{condition:False})
                self.assertNotEqual(normal,other)
                self.assertFalse(e.enabled[condition])

    def test_final_render_is_blocked_before_writing(self):
        with self.assertRaisesRegex(ValueError,'preview-only'):
            render(RenderConfig())

    def test_short_encode_decodes_and_reports_all_four_scenes(self):
        import cv2
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.mp4'
            config=RenderConfig(width=160,height=90,scene_seconds=.5,transition_seconds=.1,
                smoke=True,input_root=self.fixture.root,output_path=path,report_path=Path(folder)/'report.json')
            report=render(config)
            cap=cv2.VideoCapture(str(path));frames=0
            while cap.read()[0]:frames+=1
            cap.release()
            self.assertEqual(frames,60)
            self.assertEqual(len(report['scenes']),4)
            self.assertEqual(len(report['inheritance']),3)


if __name__=='__main__':unittest.main()
