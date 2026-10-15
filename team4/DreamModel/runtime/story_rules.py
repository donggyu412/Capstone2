"""Explicit source-law interpretations for the first two acts."""
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
