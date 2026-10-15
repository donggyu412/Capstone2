"""Causal checks for the research-directed formation runtime."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import wave
import numpy as np

from team4.DreamModel.runtime.audio_analyzer import AudioAnalyzer, prepare_preview_audio
from team4.DreamModel.archive.scene_composition import build_composition
from team4.DreamModel.archive.scene_formation import AdaptiveBalance, FormationMemory, FormationRenderer, ParticleFormation
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary
from team4.DreamModel.tests import test_input_loader as fixtures
from team4.DreamModel.runtime.input_loader import load_inputs
from team4.DreamModel.archive.transition_controller import TransitionMode, TransitionState


class FormationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.InputLoaderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scene = load_inputs(self.fixture.root).scenes[0]
        self.comp = build_composition(self.scene,160,90,SemanticLibrary())

    def group(self, seed=101):
        return ParticleFormation(self.comp,seed,1,count=700,width=48,height=27)

    def simulate(self, trace_gain=None, audio=0):
        group, memory = self.group(), FormationMemory(48,27)
        if trace_gain is not None:
            group.trace_influence = trace_gain
        for i in range(90):
            energy=group.step(memory,i/110,i/30,audio,audio*.3)
            memory.update(group.position,group.colors,energy,.98)
        return group,memory

    def test_no_full_plate_at_birth_and_joint_samples_activate(self):
        group, memory = self.group(),FormationMemory(48,27)
        energy=group.step(memory,0,0,0,0)
        self.assertEqual(float(energy.sum()),0)
        image=FormationRenderer(160,90).render(group,memory,0)
        self.assertEqual(float(image.max()),0)
        group.step(memory,.65,3,0,0)
        for label in (0,1,2):
            self.assertGreater(float(group.active[group.labels==label].sum()),0)

    def test_actual_deposits_causally_change_paths(self):
        traced,memory=self.simulate()
        untraced,_=self.simulate(trace_gain=0)
        self.assertGreater(float(memory.field.sum()),0)
        self.assertGreater(float(np.max(np.abs(traced.position-untraced.position))),1e-5)
        self.assertGreater(traced.trace_force_mean,0)

    def test_memory_retains_color_and_force_into_next_scene(self):
        _,memory=self.simulate()
        before=memory.field.copy()
        color=memory.color.copy()
        memory.retain(.35)
        np.testing.assert_allclose(memory.field,before*.35)
        np.testing.assert_allclose(memory.color,color*.35)
        remembered,fresh=self.group(),self.group()
        empty=FormationMemory(48,27)
        remembered.step(memory,.35,0,0,0)
        fresh.step(empty,.35,0,0,0)
        self.assertFalse(np.array_equal(remembered.position,fresh.position))

    def test_controller_recovers_from_lost_structure(self):
        controller=AdaptiveBalance()
        for _ in range(80): controller.update(1,1,.8,0,0)
        settled_convergence,settled_exploration=controller.convergence,controller.exploration
        for _ in range(80): controller.update(0,0,.8,0,0)
        self.assertGreater(controller.convergence,settled_convergence+.3)
        self.assertLess(controller.exploration,settled_exploration-.15)
        self.assertGreater(controller.exploration,0)

    def test_sound_changes_actual_state_without_changing_labels(self):
        silent,_=self.simulate(audio=0)
        sounding,_=self.simulate(audio=.8)
        self.assertFalse(np.allclose(silent.position,sounding.position))
        self.assertNotEqual(silent.balance.exploration,sounding.balance.exploration)
        self.assertEqual(silent.composition.plan.emotion_label,sounding.composition.plan.emotion_label)

    def test_shared_spatial_flow_deforms_both_kinds_of_material(self):
        yy,xx=np.mgrid[:90,:160]
        self.comp.rgb[:,:,0]=xx/160
        self.comp.rgb[:,:,1]=yy/90
        group,memory=self.group(),FormationMemory(48,27)
        group.active[:]=1
        group.coverage[:]=3
        renderer=FormationRenderer(160,90)
        still=renderer.render(group,memory,.8)
        group.flow[:,:,0]=.04
        moving=renderer.render(group,memory,.8)
        difference=np.mean(np.abs(still-moving),axis=2)
        for mask in (self.comp.labels==0,self.comp.labels>0):
            self.assertGreater(float(difference[mask].mean()),.001)

    def test_seed_changes_formation_and_same_seed_repeats(self):
        first,second,other=self.group(),self.group(),self.group(202)
        for group in (first,second,other):
            memory=FormationMemory(48,27)
            for i in range(25):
                energy=group.step(memory,.4,i/30,.3,.1)
                memory.update(group.position,group.colors,energy,.98)
        np.testing.assert_array_equal(first.position,second.position)
        self.assertFalse(np.array_equal(first.position,other.position))

    def test_stage_changes_only_transition_not_composition(self):
        changed=build_composition(replace(self.scene,stage="결"),160,90,SemanticLibrary())
        np.testing.assert_array_equal(self.comp.rgb,changed.rgb)
        self.assertEqual(self.comp.layout,changed.layout)

    def test_transition_ends_without_a_lingering_complete_plate(self):
        group,memory=self.simulate()
        renderer=FormationRenderer(160,90)
        for mode in TransitionMode:
            image=renderer.render(group,memory,.99,TransitionState(mode,1))
            self.assertEqual(float(image.max()),0)

    def test_no_layout_is_claimed_as_upstream_truth(self):
        self.assertTrue(all("approximation" in item["status"] for item in self.comp.layout))
        self.assertEqual({item["object_id"] for item in self.comp.layout},{"1:1","1:2"})

    def test_audio_excerpt_clock_is_exact_and_not_time_stretched(self):
        with tempfile.TemporaryDirectory() as directory:
            source,output=Path(directory)/"source.wav",Path(directory)/"preview.wav"
            rate=16000
            signal=np.concatenate([.2*np.sin(2*np.pi*f*np.arange(rate)/rate) for f in (220,330,440,550)])
            with wave.open(str(source),"wb") as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate)
                w.writeframes((signal*32767).astype("<i2").tobytes())
            path,report=prepare_preview_audio(source,output,.25,preview=True)
            self.assertEqual([s["source_start"] for s in report["segments"]],[.375,1.375,2.375,3.375])
            with wave.open(str(path),"rb") as w:
                self.assertEqual(w.getnframes()/w.getframerate(),1)
                audio=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2").reshape(-1,2)[:,0]
                rate=w.getframerate()
            for index,target in enumerate((220,330,440,550)):
                segment=audio[round(index*.25*rate):round((index+1)*.25*rate)]
                peak=np.fft.rfftfreq(len(segment),1/rate)[np.argmax(abs(np.fft.rfft(segment)))]
                self.assertAlmostEqual(peak,target,delta=4)
            features=AudioAnalyzer(path)
            self.assertGreater(features.features(.12)[0],.3)


if __name__=="__main__":
    unittest.main()
