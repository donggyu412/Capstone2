"""Preview-only geometric evolution, preserving upstream inputs and old renders."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from team4.DreamModel.runtime.audio_analyzer import AudioAnalyzer, prepare_preview_audio
from team4.DreamModel.config import RenderConfig
from team4.DreamModel.archive.frame_renderer import VideoWriter
from team4.DreamModel.runtime.input_loader import load_inputs
from team4.DreamModel.archive.memory_grammar import MemoryField
from team4.DreamModel.archive.geometric_evolution import Evolution, GeometricRenderer
from team4.DreamModel.archive.run_report import file_digest
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary


def render(config: RenderConfig, audio_path: Path | None = None) -> dict:
    if not config.smoke or config.scene_seconds > 5:
        raise ValueError('Geometric evolution is preview-only: use --preview (20 s) or --smoke (16 s).')
    started = time.perf_counter()
    cv2.setNumThreads(1)
    bundle = load_inputs(config.input_root, audio_path)
    library = SemanticLibrary(config.semantic_config)
    fields = [MemoryField(scene, library) for scene in bundle.scenes]
    audio_file, timeline = prepare_preview_audio(bundle.audio_path,
        config.output_path.with_name(config.output_path.stem + '_audio.wav'), config.scene_seconds, preview=True)
    audio = AudioAnalyzer(audio_file)
    enabled = {k: config.conditioning_off != k for k in ('story', 'emotion', 'sound')}
    engine = Evolution(fields, config.seed, **enabled)
    renderer = GeometricRenderer(config.width, config.height)
    state_hash, frame_hash = hashlib.sha256(), hashlib.sha256()
    samples, scenes = [], []
    with VideoWriter(config.output_path, config.width, config.height, config.fps,
                     audio_path=audio_file, expected_frames=config.total_frames) as writer:
        for i, scene in enumerate(bundle.scenes):
            engine.enter_scene(i)
            start_events = len(engine.events)
            print(f'[scene {i+1}/4] geometric organism evolution', flush=True)
            for local in range(config.scene_frames):
                frame = i * config.scene_frames + local
                rms, onset = audio.features(frame / config.fps)
                engine.step(local / max(1, config.scene_frames - 1), 1 / config.fps, rms, onset)
                pixels = renderer.render(engine)
                writer.write(pixels)
                frame_hash.update(pixels.tobytes())
                for o in engine.population:
                    state_hash.update(o.rest.astype('<f8').tobytes())
                    state_hash.update(np.asarray(o.connections, dtype='<i4').tobytes())
                    state_hash.update(np.asarray([o.energy, o.novelty, o.fitness], dtype='<f8').tobytes())
                if local % 10 == 0 or local == config.scene_frames - 1:
                    samples.append({'frame': frame, 'scene': i + 1, **engine.snapshot()})
            scenes.append({'scene_id': scene.scene_id, 'title': scene.title, 'stage': scene.stage,
                'emotion_label': scene.emotion_label, 'intensity': scene.emotion_intensity,
                'event_counts': dict(Counter(e['type'] for e in engine.events[start_events:]))})
    report = {'model': 'DreamModel', 'version': '2.0.0-preview', 'status': 'rendered; requires visual review',
        'mechanism': 'Memory-Conditioned Geometric Evolution',
        'resolution': [config.width, config.height], 'fps': config.fps, 'duration': config.duration,
        'total_frames': config.total_frames, 'seed': config.seed, 'conditioning': enabled,
        'input_files': [{'path': str(p), 'sha256': file_digest(p)} for p in bundle.input_files],
        'audio': {**audio.as_report(), 'timeline': timeline,
                  'conditioning_disabled_keeps_soundtrack': config.conditioning_off == 'sound'},
        'memory_fields': [m.report() for m in fields], 'scenes': scenes, 'samples': samples,
        'inheritance': engine.transfers, 'events': engine.events,
        'event_counts': dict(Counter(e['type'] for e in engine.events)),
        'raw_frames_sha256': frame_hash.hexdigest(), 'state_sha256': state_hash.hexdigest(),
        'output_file': str(config.output_path), 'elapsed_seconds': time.perf_counter() - started,
        'implementation_files': [{'path': str(p), 'sha256': file_digest(p)}
                                 for p in sorted(Path(__file__).parent.glob('*.py'))],
        'assumptions': ['Placement and scale are artistic regions, not provided coordinates',
            'Contour turns and coarse spatial lines form a finite grammar; no target RGB rendering',
            'Fear intensity mapping is an artistic hypothesis, not an emotion classifier',
            'Four equal audio sections assumed; no upstream cue sheet supplied',
            'Finite population and grammar; does not demonstrate unbounded open-endedness'],
        'warnings': list(bundle.warnings)}
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'[complete] {config.output_path}', flush=True)
    return report
