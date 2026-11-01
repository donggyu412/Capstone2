"""Emotion-dependent motion and measured temporal guidance from the input video.

Video samples control illumination and tempo of generated material. They are
never composited as a second background, and cannot reveal unborn cells.
"""
from pathlib import Path
import hashlib
import math
import subprocess

import cv2
import numpy as np


def emotion_motion(emotion, seconds, source_energy=0.0):
    """Art-directed response to 10/29 feedback; seconds follows the whole act."""
    t = float(seconds)
    pulse = lambda centre, width: math.exp(-.5*((t-centre)/width)**2)
    # Unequal pauses and bursts avoid using one oscillator for all four acts.
    if emotion == 'surprise':
        burst = min(1., sum(pulse(c,w) for c,w in [(6.8,.65),(17.5,1.2),(28.3,.9),(43.8,.8),(56.1,1.25),(67.2,.65)]))
        speed = .14+2.65*burst+.24*source_energy
        amplitude = .30+1.35*burst
        mesh = 18+100*burst
        mode = 'pause_then_burst'
    elif emotion in ('fear','angry','disgust'):
        burst = min(1., sum(pulse(c,w) for c,w in [(4.,1.1),(11.7,1.8),(20.3,.85),(31.2,2.1),(41.6,1.3),(49.4,.9),(58.8,2.),(69.1,1.2)]))
        speed = .35+2.40*burst+.36*source_energy
        amplitude = .70+1.15*burst
        mesh = 30+90*(.25+.75*burst)
        mode = 'surge_recoil_wave'
    elif emotion == 'happy':
        burst = .5+.5*math.sin(t*.57+.60*math.sin(t*.13))
        speed = .62+.65*burst+.16*source_energy
        amplitude = .62+.34*burst
        mesh = 18+45*burst
        mode = 'open_and_lift'
    elif emotion == 'sad':
        burst = pulse(25.,4.5)*.45+pulse(58.,6.)*.25
        speed = .045+.16*burst+.05*source_energy
        amplitude = .10+.18*burst
        mesh = 18+66*(.5+.5*math.sin(t*.095-.9))
        mode = 'long_stillness_slow_retreat'
    else:
        burst = .5+.5*math.sin(t*.24)
        speed, amplitude, mesh = .35+.25*burst,.38+.25*burst,18+42*burst
        mode = 'quiet_irregular_drift'
    return dict(speed=float(speed),amplitude=float(amplitude),mesh_px=float(mesh),
                burst=float(burst),mode=mode,source_energy=float(source_energy))


class VideoRhythm:
    """Read the entire input timeline, including its region-wise light changes."""
    sample_fps = 10
    width, height = 64, 36

    def __init__(self, video, cache_dir, ffmpeg, scene_sec=75.):
        self.video = Path(video).resolve()
        stat = self.video.stat()
        identity = f'{self.video}|{stat.st_size}|{stat.st_mtime_ns}|v13a'
        key = hashlib.sha256(identity.encode()).hexdigest()[:20]
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True,exist_ok=True)
        cache = cache_dir/f'video_rhythm_{key}.npz'
        if cache.exists():
            data = np.load(cache)
            self.frames = data['frames']
            self.energy = data['energy']
        else:
            result = subprocess.run([str(ffmpeg),'-v','error','-i',str(self.video),
                '-vf',f'scale={self.width}:{self.height},fps={self.sample_fps}',
                '-an','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True)
            frames = np.frombuffer(result.stdout,np.uint8).reshape(-1,self.height,self.width,3).astype(np.float32)/255.
            energy = np.r_[0.,np.abs(np.diff(frames,axis=0)).mean((1,2,3))].astype(np.float32)
            self.energy = energy
            self.frames = np.stack([cv2.GaussianBlur(f,(0,0),1.4) for f in frames]).astype(np.float16)
            np.savez_compressed(cache,frames=self.frames,energy=self.energy)
        self.scene_sec = float(scene_sec)
        required = round(self.scene_sec*4*self.sample_fps)
        if len(self.frames) < required-1:
            raise ValueError(f'Background video is shorter than four {scene_sec}s acts')
        self.references = [self.frames[min(len(self.frames)-1,round((i+.5)*self.scene_sec*self.sample_fps))].astype(np.float32) for i in range(4)]
        self.energy_scale = max(float(np.percentile(self.energy,90)),.002)
        self.report = dict(source=str(self.video),samples=len(self.frames),sample_fps=self.sample_fps,
            method='low-frequency regional illumination and temporal motion energy; no source image overlay',
            act_motion_mean=[float(self.energy[round(i*self.scene_sec*self.sample_fps):round((i+1)*self.scene_sec*self.sample_fps)].mean()) for i in range(4)])

    def sample(self, act, seconds):
        frame = (act*self.scene_sec+seconds)*self.sample_fps
        lo = min(len(self.frames)-1,max(0,int(frame)))
        hi = min(len(self.frames)-1,lo+1)
        a = frame-lo
        current = self.frames[lo].astype(np.float32)*(1-a)+self.frames[hi].astype(np.float32)*a
        reference = self.references[act]
        # Ratios carry the delivered video's rhythm; only owned RGB is modulated.
        gain = np.clip((current+.10)/(reference+.10),.58,1.60)
        energy = float(np.clip((self.energy[lo]*(1-a)+self.energy[hi]*a)/self.energy_scale,0,1.5))
        return gain.astype(np.float32),energy
