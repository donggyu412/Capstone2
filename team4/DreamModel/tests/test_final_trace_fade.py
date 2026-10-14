"""Unfinished grammar strokes obey the same scene lifetime as solid material."""
import unittest
from types import SimpleNamespace
import numpy as np
from team4.DreamModel.dream_surfaces import DreamSurfaces


class FinalTraceFadeTests(unittest.TestCase):
    def trace_energy(self,sid,t,distance=0.):
        score=SimpleNamespace(warp=lambda points,*args:points)
        renderer=DreamSurfaces([],480,270,score)
        patch=SimpleNamespace(root=np.array([.30,.50]),center=np.array([.70,.50]),
                              color=np.array([.6,.7,.8]),distance=distance)
        group=SimpleNamespace(kind='journal',patches=[patch])
        state={'objects':{'journal':np.array([.5])},'roots':{'journal':np.array([patch.root])}}
        world=SimpleNamespace(time=t,controls={'journal':np.zeros((9,9,2))})
        canvas=np.zeros((270,480,3),np.float32)
        renderer.draw_grammar_trace(canvas,group,sid,state,world)
        return float(canvas.sum())

    def test_final_primitive_strokes_fade_and_leave_last_frame_empty(self):
        before=self.trace_energy(3,280)
        fading=self.trace_energy(3,287)
        self.assertGreater(before,fading)
        self.assertGreater(fading,0)
        # Include the furthest region, whose final recession completes last.
        for distance in (0.,.5,1.):
            self.assertEqual(self.trace_energy(3,8999/30,distance),0)

    def test_outgoing_primitive_strokes_disappear_before_state_expires(self):
        self.assertGreater(self.trace_energy(0,70,1.),0)
        for distance in (0.,.5,1.):
            self.assertEqual(self.trace_energy(0,2849/30,distance),0)


if __name__=='__main__':unittest.main()
