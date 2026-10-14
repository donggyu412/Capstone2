"""Joint scene formation runtime and observable provenance."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from PIL import Image

from team4.DreamModel.runtime.audio_analyzer import AudioAnalyzer, prepare_preview_audio
from team4.DreamModel.config import MODEL_VERSION, RenderConfig
from team4.DreamModel.archive.frame_renderer import VideoWriter
from team4.DreamModel.runtime.input_loader import load_inputs
from team4.DreamModel.archive.run_report import file_digest, readable_path
from team4.DreamModel.archive.scene_composition import build_composition
from team4.DreamModel.archive.scene_formation import AdaptiveBalance, FormationMemory, FormationRenderer, ParticleFormation
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary
from team4.DreamModel.archive.transition_controller import TransitionController, TransitionMode, mode_for_stage


def render(config: RenderConfig, audio_path: Path | None = None) -> dict:
    started = time.perf_counter()
    cv2.setNumThreads(1)
    bundle = load_inputs(config.input_root, audio_path)
    library = SemanticLibrary(config.semantic_config)
    compositions = [build_composition(s, config.width, config.height, library) for s in bundle.scenes]
    for warning in bundle.warnings:
        print(f"[안내] {warning}", flush=True)
    audio_file, audio_timing = prepare_preview_audio(
        bundle.audio_path, config.output_path.with_name(config.output_path.stem + "_audio.wav"),
        config.scene_seconds, preview=config.smoke)
    audio = AudioAnalyzer(audio_file)
    memory = FormationMemory(config.trace_width, config.trace_height)
    renderer = FormationRenderer(config.width, config.height)
    transitions = TransitionController(config.transition_seconds)
    groups = {}
    count = min(9000, max(1800, round(config.width*config.height/72)))
    state_hash, frame_hash = hashlib.sha256(), hashlib.sha256()
    reports, carryovers = [], []
    reference_dir = config.output_path.with_name(config.output_path.stem + "_references")
    reference_dir.mkdir(parents=True, exist_ok=True)
    for index, comp in enumerate(compositions):
        Image.fromarray((np.clip(comp.rgb,0,1)*255).astype(np.uint8)).save(reference_dir/f"scene_{index+1:02d}.png")

    def group(index):
        if index not in groups:
            prior = groups[index-1].balance if index-1 in groups else AdaptiveBalance()
            inherited = AdaptiveBalance(prior.convergence, prior.exploration, prior.readability)
            groups[index] = ParticleFormation(compositions[index], config.seed, bundle.scenes[index].scene_id,
                                              count=count, width=config.trace_width, height=config.trace_height,
                                              balance=inherited)
        return groups[index]

    with VideoWriter(config.output_path, config.width, config.height, config.fps,
                     audio_path=audio_file, expected_frames=config.total_frames) as writer:
        for index, scene in enumerate(bundle.scenes):
            if index:
                before, color_before = float(memory.field.sum()), float(memory.color.sum())
                memory.retain(config.memory_retention)
                carryovers.append({"into_scene_id": scene.scene_id, "before": before,
                                   "after": float(memory.field.sum()), "fraction": config.memory_retention,
                                   "color_before": color_before, "color_after": float(memory.color.sum())})
            active = group(index)
            item = {"scene_id":scene.scene_id, "title":scene.title, "story":scene.story,
                    "stage":scene.stage, "emotion_label":scene.emotion_label,
                    "emotion_intensity":scene.emotion_intensity, "start_frame":index*config.scene_frames,
                    "duration":config.scene_seconds, "transition_mode":mode_for_stage(scene.stage).value,
                    "transition_start_frame":(index+1)*config.scene_frames-round(config.transition_seconds*config.fps),
                    "layout":compositions[index].layout, "composition_reference":readable_path(reference_dir/f"scene_{index+1:02d}.png"),
                    "samples":[], "mean_activity":0.0, "mean_exploration_strength":0.0, "mean_audio_rms":0.0}
            print(f"[장면 {scene.scene_id}/4] {scene.stage} · 배경/오브제 공동 형성 · {count} samples",flush=True)
            for local in range(config.scene_frames):
                frame = index*config.scene_frames+local
                seconds = local/config.fps
                fraction = local/max(1,config.scene_frames-1)
                effective_fraction = fraction if index == 0 else .14+.86*fraction
                transition = transitions.state_for_frame(scene.stage,local,config.scene_frames,config.fps)
                rms,onset = audio.features(frame/config.fps)
                energy = active.step(memory,effective_fraction,seconds,rms,onset,transition)
                particles, colors, energies = [active.position],[active.colors],[energy]
                incoming = group(index+1) if transition is not None and index<3 else None
                if incoming is not None:
                    incoming_fraction = .14*transition.smooth_progress
                    incoming_energy = incoming.step(memory,incoming_fraction,seconds-config.scene_seconds,rms,onset)
                    particles.append(incoming.position)
                    colors.append(incoming.colors)
                    energies.append(incoming_energy*.55)
                # Every particle reads old H(t); one deposit/decay updates it.
                trace_decay = .965 + .018*scene.emotion_intensity + .005*rms
                memory.update(np.concatenate(particles),np.concatenate(colors),np.concatenate(energies),trace_decay)
                pixels = renderer.render(active,memory,effective_fraction,transition)
                if incoming is not None:
                    next_pixels = renderer.render(incoming,memory,incoming_fraction)
                    gain = transition.smooth_progress
                    if transition.mode == TransitionMode.ACCUMULATION:
                        gain = min(1.,gain*1.25)
                    pixels += next_pixels*gain
                pixels = (np.clip(pixels,0,1)*255).astype(np.uint8)
                writer.write(pixels)
                state_hash.update(np.asarray(active.position,dtype="<f8").tobytes())
                state_hash.update(np.asarray(active.velocity,dtype="<f8").tobytes())
                state_hash.update(memory.field.astype("<f4").tobytes())
                state_hash.update(memory.color.astype("<f4").tobytes())
                state_hash.update(active.coverage.astype("<f4").tobytes())
                state_hash.update(np.asarray([active.balance.convergence,active.balance.exploration,
                                              active.balance.readability],dtype="<f8").tobytes())
                frame_hash.update(pixels.tobytes())
                snapshot = active.snapshot()
                item["mean_activity"] += float(np.mean(np.linalg.norm(active.velocity,axis=1)))
                item["mean_exploration_strength"] += active.balance.exploration
                item["mean_audio_rms"] += rms
                if local % 15 == 0 or local==config.scene_frames-1:
                    item["samples"].append({"frame":frame,"trace_mass":float(memory.field.sum()),**snapshot})
            for key in ("mean_activity","mean_exploration_strength","mean_audio_rms"):
                item[key] /= config.scene_frames
            reports.append(item)
    report = {
        "model":"DreamModel", "version":MODEL_VERSION, "status":"complete",
        "completion_scope":"technical preview; visual research criteria require review",
        "mode":"preview" if config.smoke else "final",
        "seed":config.seed, "resolution":[config.width,config.height], "fps":config.fps,
        "duration":config.duration,"total_frames":config.total_frames,"scene_duration":config.scene_seconds,
        "transition_window_seconds":config.transition_seconds,
        "mean_activity":float(np.mean([s["mean_activity"] for s in reports])),
        "mean_exploration_strength":float(np.mean([s["mean_exploration_strength"] for s in reports])),
        "scene_memory_carryovers":carryovers, "scenes":reports,
        "audio":{**audio.as_report(),"timeline":audio_timing},
        "input_files":[{"path":readable_path(p),"sha256":file_digest(p)} for p in bundle.input_files],
        "implementation_files":[{"path":readable_path(p),"sha256":file_digest(p)}
                                for p in sorted(Path(__file__).parent.glob("*.py"))],
        "semantic_config":{"path":str(library.path),"sha256":file_digest(library.path),
                           "scene_plans":[c.plan.as_report() for c in compositions]},
        "mechanisms":["Scene-Guided Particle Morphogenesis","Stigmergic Trace Memory","Adaptive Convergence–Exploration"],
        "trace_memory":{"retention":config.memory_retention,"decay":"0.965 + 0.018*input_intensity + 0.005*RMS",
                        "numeric_field":[config.trace_width,config.trace_height],"is_cellular_automaton":False},
        "readability_proxy":"0.65*particle structural coherence + 0.35*local sample coverage; not human recognition",
        "source_layout":"absent; source-backed artistic approximate composition",
        "output_file":readable_path(config.output_path),
        "state_sha256":state_hash.hexdigest(),"raw_frames_sha256":frame_hash.hexdigest(),
        "video_sha256":file_digest(config.output_path), "elapsed_render_seconds":time.perf_counter()-started,
        "environment":{"numpy":np.__version__,"opencv":cv2.__version__},
        "warnings":list(bundle.warnings),
        "limits":["No full collective EEG dynamics supplied; one emotion label per scene",
                  "Bounded source-guided stochastic formation, not unrestricted open-ended evolution",
                  "Original Team3 backgrounds and some objects are abstract",
                  "Sound scene alignment assumes four equal source sections without a cue sheet"],
    }
    config.report_path.parent.mkdir(parents=True,exist_ok=True)
    config.report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(f"[완료] {config.total_frames} frames / {config.duration:g}초: {config.output_path}",flush=True)
    print(f"[보고서] {config.report_path}",flush=True)
    return report
