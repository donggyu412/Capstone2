"""Auditable interpretation of supplied laws. No law is invented or auto-approved.

Timing is artistic direction on the original 75-second clock, not upstream
timecodes. Late scene-two events remain late even in a short transition preview.
"""
from dataclasses import dataclass
import math
import numpy as np


def smooth(x):
    x = float(np.clip(x, 0, 1))
    return x*x*x*(x*(x*6-15)+10)


@dataclass(frozen=True)
class Event:
    scene: int
    law: str
    channel: str
    start: float
    end: float
    implementation: str


# Substring predicates only identify explicitly supplied statements; they do
# not infer unlisted physics. The first two scenes are the renderer's scope.
RULES = (
    (1, ('거리', '멀어'), 'recede', 25, 75, 'continuous perspective field dilation'),
    (1, ('소리', '크기'), 'audio_space', 0, 75, 'smoothed audio onset-rate biases room dilation; acoustic proxy, not droplet recognition'),
    (1, ('발끝', '떠'), 'float', 20, 75, 'figure bottom remains above the estimated floor plane'),
    (1, ('마지막 장', '넘어'), 'page_turn', 65, 74, 'curved textured page rotates around its retained spine'),
    (1, ('얼룩', '사라'), 'erase', 69, 74, 'ink on the turning surface dissolves before transfer'),
    (2, ('물방울', '사라'), 'drop', 75, 150, 'drop surface reaches floor then collapses; no added impact audio'),
    (2, ('높이', '변하지'), 'constant_pool', 75, 132, 'incoming drops do not accumulate pool depth'),
    (2, ('바람', '팔락'), 'flutter', 96, 150, 'pinned paper free edge bends on a slow cycle'),
    (2, ('글씨', '넘길'), 'writing', 96, 125, 'ink visibility follows the same paper-turn phase'),
    (2, ('그림자', '미끄'), 'glide', 79, 123, 'inherited figure approaches continuously without floor contact'),
    (2, ('종이', '글자', '먼저'), 'erase_before_water', 124, 134, 'ink erases before detached sheet reaches floor'),
    (2, ('손', '높이', '변화'), 'hand_pool', 130, 142, 'pool height changes only after hand contact time'),
)


class StoryEvents:
    def __init__(self, scenes):
        self.events = []
        self.unsupported = []
        for scene in scenes:
            for law in scene.physics_laws:
                rule = next((r for r in RULES if r[0] == scene.scene_id and all(k in law for k in r[1])), None)
                if rule:
                    self.events.append(Event(scene.scene_id, law, *rule[2:]))
                else:
                    self.unsupported.append({'scene': scene.scene_id, 'law': law,
                        'reason': 'scene outside two-scene preview renderer' if scene.scene_id > 2 else 'no implemented interpretation'})
        # This relation occurs in prose, not in the first scene's law array.
        self.reach_evidence = next((p for p in scenes[0].story.split('\n\n')
            if '항해일지' in p and '손을 뻗' in p), '')

    def enabled(self, channel):
        return any(e.channel == channel for e in self.events)

    def progress(self, channel, seconds):
        event = next((e for e in self.events if e.channel == channel), None)
        return smooth((seconds-event.start)/(event.end-event.start)) if event else 0.

    def channels(self, seconds, *, enabled=True):
        if not enabled:
            return {k: 0. for k in ('recede','audio_space','float','page_turn','erase','drop','constant_pool',
                'flutter','writing','glide','erase_before_water','hand_pool','reach')}
        values = {e.channel:self.progress(e.channel,seconds) for e in self.events}
        values['reach'] = smooth((seconds-49)/18) if self.reach_evidence else 0.
        values['audio_space'] = float(self.enabled('audio_space'))
        values['float'] = float(self.enabled('float'))
        values['drop'] = float(self.enabled('drop') and 75 <= seconds < 150)
        values['flutter'] = ((.5-.5*math.cos((seconds-96)*math.pi/4)) * smooth((seconds-96)/4)
            if self.enabled('flutter') else 0.)
        return values

    def report(self, start=65, end=85):
        return {'timing_basis': 'artistic scheduling of supplied events within 75-second scenes; no accelerated late events',
            'laws':[{'scene':e.scene,'law':e.law,'channel':e.channel,'implemented':True,
                'scheduled_original_seconds':[e.start,e.end],
                'active_in_preview':max(start,e.start)<min(end,e.end),
                'implementation':e.implementation} for e in self.events],
            'unsupported':self.unsupported,'prose_relationship':self.reach_evidence,
            'note':'Implemented channels must also be exercised by the renderer; this report is not a visual acceptance score.'}
