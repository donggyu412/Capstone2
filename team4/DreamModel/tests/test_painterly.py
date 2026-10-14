"""Material continuity and the original-speed transition preview contract."""
from dataclasses import replace
import unittest
import numpy as np
from team4.DreamModel.archive.brush_painter import BrushMemory,BrushPainter
from team4.DreamModel.config import RenderConfig
from team4.DreamModel.runtime.input_loader import load_inputs
from team4.DreamModel.main import parse_config
from team4.DreamModel.archive.painterly_pipeline import render
from team4.DreamModel.archive.scene_composition import build_composition
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary
from team4.DreamModel.archive.memory_grammar import MemoryField
from team4.DreamModel.archive.evolving_brush import EvolvingBrush
from team4.DreamModel.tests import test_input_loader as fixtures


class PainterlyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.InputLoaderTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        scene=load_inputs(self.fixture.root).scenes[0]
        composition=build_composition(scene,160,90,SemanticLibrary())
        self.memory=BrushMemory(composition,101)

    def test_cli_inspects_birth_at_original_speed_before_transition(self):
        config,_=parse_config(['--preview'])
        self.assertEqual((config.scene_count,config.scene_seconds,config.total_frames),(1,75,600))
        self.assertEqual((config.preview_start_seconds,config.preview_seconds),(0,20))
        self.assertEqual((config.width,config.height,config.duration),(960,540,20))

    def test_inherit_preserves_pigment_and_direction_exactly(self):
        painter=BrushPainter(160,90)
        for frame in range(30):painter.step(self.memory,.5,frame/30,1/30,.5,0)
        pigment=painter.canvas.copy();direction=painter.direction.copy()
        painter.inherit()
        np.testing.assert_array_equal(pigment,painter.canvas)
        np.testing.assert_array_equal(direction,painter.direction)
        self.assertGreater(painter.inherited_stroke_count,0)

    def test_local_brush_deposits_pigment_without_replacing_whole_canvas(self):
        painter=BrushPainter(160,90);before=painter.canvas.copy()
        painter.stroke(self.memory,80,45,5,20,.5,1,.4)
        changed=np.any(painter.canvas!=before,axis=2)
        self.assertGreater(changed.sum(),10)
        self.assertLess(changed.sum(),160*90*.15)
        self.assertGreater(np.linalg.norm(painter.direction),0)

    def test_inherited_direction_changes_next_stroke(self):
        a=BrushPainter(160,90);b=BrushPainter(160,90)
        a.direction[:,:,0]=1;b.direction[:,:,1]=1
        a.inherited_stroke_count=b.inherited_stroke_count=10
        a.stroke(self.memory,80,45,5,30,.6,1,.2)
        b.stroke(self.memory,80,45,5,30,.6,1,.2)
        self.assertFalse(np.array_equal(a.canvas,b.canvas))

    def test_no_final_or_accidental_four_scene_render(self):
        with self.assertRaisesRegex(ValueError,'preview only'):render(RenderConfig())
        with self.assertRaisesRegex(ValueError,'75-second'):render(replace(RenderConfig(),smoke=True))

    def test_soft_form_develops_gradually_and_survives_transition(self):
        p=BrushPainter(160,90,soft=True);before=p.canvas.copy()
        p.stroke(self.memory,80,45,12,40,.6,1,.5,duration=3.)
        np.testing.assert_array_equal(p.canvas,before)
        p.advance_wet_strokes(1/30)
        first=float(np.abs(p.canvas-before).sum())
        p.inherit();self.assertEqual(len(p.wet_strokes),1)
        for _ in range(90):p.advance_wet_strokes(1/30)
        self.assertGreater(float(np.abs(p.canvas-before).sum()),first*5)
        self.assertEqual(len(p.wet_strokes),0)

    def test_live_geometry_affects_material_without_drawing_full_connections(self):
        field=MemoryField(load_inputs(self.fixture.root).scenes[0],SemanticLibrary())
        images=[]
        for y,dying in ((.3,False),(.7,False),(.3,True)):
            coupling=EvolvingBrush([field],101)
            organism=coupling.engine.birth(field.motifs[0])
            organism.controlPoints=np.array([[.1,y],[.9,y]])
            organism.connections=[(0,1)]
            organism.colorTraits=np.array([.7,.7,.7])
            organism.dying=dying
            coupling.credits[organism.uid]=1.
            painter=BrushPainter(160,90,soft=True)
            initial=painter.canvas.copy()
            coupling.paint(painter,self.memory,.5,1/30,.5)
            for _ in range(240):painter.advance_wet_strokes(1/30)
            images.append(painter.canvas.copy())
            changed=np.any(painter.canvas!=initial,axis=2)
            if dying:
                self.assertFalse(changed.any())
            else:
                ys,xs=np.where(changed)
                self.assertGreater(len(xs),0)
                self.assertLess(np.ptp(xs),160*.25)
        self.assertFalse(np.array_equal(images[0],images[1]))


if __name__=='__main__':unittest.main()
