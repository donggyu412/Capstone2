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


def emotion_motion(emotion, seconds, source_energy=0.0, story=None):
    """Unequal holds and surges follow story beats, not a repeating oscillator."""
    t = float(seconds)
    # (seconds, rate): unequal spacing and repeated medium/slow holds prevent
    # an alternating fast/slow rhythm. Story controls below retain event timing.
    timing = {
        'surprise': [(0,.05),(6,.05),(10,.35),(14,.8),(20,.8),(21,3.1),(23,1.1),
                     (28,.08),(32,.08),(40,.55),(43,2.4),(49,.9),(57,.3),(65,1.4),(75,.25)],
        'fear': [(0,.35),(5,.35),(7,2.6),(13,1.2),(18,1.2),(19,.08),(24,.08),
                 (30,2.1),(38,.65),(47,.65),(49,3.3),(56,1.8),(63,3.1),(66,.15),(75,.4)],
        'happy': [(0,.18),(9,.18),(16,.7),(24,1.9),(30,1.9),(38,.5),(47,.15),
                  (54,.15),(61,1.1),(67,2.4),(72,.85),(75,.85)],
        'sad': [(0,.55),(7,1.3),(13,.35),(23,.1),(29,.04),(39,.04),(45,.4),
                (50,.18),(56,.18),(59,.85),(65,.12),(75,.05)],
        'neutral': [(0,.15),(12,.15),(18,.7),(27,.7),(31,1.8),(37,.3),(51,.3),
                    (58,.9),(64,.12),(75,.12)],
    }
    keys=timing.get('fear' if emotion in ('angry','disgust') else emotion,timing['neutral'])
    index=int(np.clip(np.searchsorted([k[0] for k in keys],t,side='right')-1,0,len(keys)-2))
    a,x=keys[index];b,y=keys[index+1]
    u=float(np.clip((t-a)/(b-a),0,1))
    speed=x+(y-x)*u*u*(3-2*u)
    story=story or {}
    speed*=.85+.30*float(story.get('tension',.5))+.15*float(story.get('travel',0.))
    beat=story.get('beat','')
    if beat in ('discovery','relief'):speed*=.45
    elif beat in ('aversion','oxygen_pressure'):speed*=1.25
    speed*=1-.94*float(np.clip(story.get('pause',0.),0,1))
    speed=float(np.clip(speed*(1+.08*source_energy),.025,3.8))
    burst=float(np.clip((speed-.1)/3.,0,1))
    # Keep the existing emotion-specific displacement and cell-size ranges.
    if emotion == 'surprise':
        amplitude = .30+1.35*burst
        mesh = 18+100*burst
        mode = 'pause_then_burst'
    elif emotion in ('fear','angry','disgust'):
        amplitude = .70+1.15*burst
        mesh = 30+90*(.25+.75*burst)
        mode = 'surge_recoil_wave'
    elif emotion == 'happy':
        amplitude = .62+.34*burst
        mesh = 18+45*burst
        mode = 'open_and_lift'
    elif emotion == 'sad':
        amplitude = .10+.18*burst
        mesh = 18+66*(.5+.5*math.sin(t*.095-.9))
        mode = 'long_stillness_slow_retreat'
    else:
        amplitude, mesh = .38+.25*burst,18+42*burst
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
