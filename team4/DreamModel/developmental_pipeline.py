"""Original-clock two-scene preview with actual input/event accounting."""
from pathlib import Path
import hashlib
import json
import time
import cv2
import numpy as np
from PIL import Image
from .config import REPO_ROOT
from .input_loader import load_inputs
from .semantic_conditioning import SemanticLibrary
from .story_events import StoryEvents
from .developmental_world import DevelopmentalWorld
from .developmental_renderer import VisualMemories,DevelopmentalRenderer
from .audio_analyzer import AudioAnalyzer
from .painterly_pipeline import prepare_audio
from .frame_renderer import VideoWriter
from .run_report import file_digest


def prepare(config,audio_path=None,**flags):
    bundle=load_inputs(config.input_root,audio_path)
    library=SemanticLibrary(config.semantic_config)
    plans=[library.plan(s) for s in bundle.scenes]
    paths=[REPO_ROOT/'team3/background/input/storyboard'/f'scene_{s.scene_id:02d}.png' for s in bundle.scenes]
    for path in paths:
        if not path.is_file():raise ValueError(f'Missing supplied spatial reference: {path}')
    memories=VisualMemories(bundle,plans,paths)
    events=StoryEvents(bundle.scenes)
    if config.conditioning_off:flags[config.conditioning_off]=False
    world=DevelopmentalWorld(plans,config.seed,config.audience,memories=memories,events=events,**flags)
    renderer=DevelopmentalRenderer(config.width,config.height,memories,config.seed)
    return bundle,plans,memories,events,world,renderer


def render(config,audio_path:Path|None=None):
    if not config.smoke:raise ValueError('This revision is a transition preview only; --final is disabled.')
    if (config.scene_count,config.scene_seconds,config.preview_start_seconds,config.preview_seconds)!=(2,75,65,20):
        raise ValueError('Preview requires two 75-second scenes, capturing exactly original seconds 65–85.')
    if config.transition_seconds!=20:
        raise ValueError('This reviewed transition uses a 20-second overlap centered on 75 seconds.')
    cv2.setNumThreads(1);started=time.perf_counter()
    bundle,plans,memories,events,world,renderer=prepare(config,audio_path)
    audio=AudioAnalyzer(bundle.audio_path)
    audio_file,timing=prepare_audio(bundle.audio_path,
        config.output_path.with_name(config.output_path.stem+'_audio.wav'))
    samples=[];digest=hashlib.sha256();captured=[];deltas=[];previous=None
    source_start=round(config.preview_start_seconds*config.fps)
    end=source_start+config.total_frames
    with VideoWriter(config.output_path,config.width,config.height,config.fps,
                     audio_path=audio_file,expected_frames=config.total_frames,
                     crf=18,keyframe_interval=config.total_frames) as writer:
        for frame in range(end):
            t=frame/config.fps
            world.step(t,1/config.fps,*audio.features(t))
            if frame==0:renderer.background(world)
            if frame>=source_start:
                pixels=renderer.render(world);writer.write(pixels);digest.update(pixels.tobytes())
                if previous is not None:deltas.append(float(np.mean(np.abs(pixels.astype(float)-previous))))
                previous=pixels.astype(float)
                if (frame-source_start)%30==0 or frame==end-1:
                    samples.append({**world.snapshot(),'renderer':renderer.stats.copy()})
                if frame-source_start in (0,150,300,450,599):
                    captured.append((t,Image.fromarray(pixels.copy())))
            if frame%300==0:print(f'[state] original {t:.0f}s / '+('warming state' if frame<source_start else 'encoding'),flush=True)
    report={
        'model':'DreamModel story-conditioned developmental surfaces',
        'status':'bounded source-conditioned 2.5D prototype; visual acceptance remains separate from tests',
        'output_file':str(config.output_path),'resolution':[config.width,config.height],
        'fps':30,'duration':20,'total_frames':600,'source_window':[65,85],'nominal_boundary':75,
        'playback_rate':1.,'simulation_dt_seconds':1/30,'scene_duration_seconds':75,
        'encoding':{'codec':'H.264','crf':18,'keyframe_interval':config.total_frames},
        'warm_up_frames':source_start,'seed':config.seed,
        'input_contract':{
            'flow':'Team1 emotion -> Team2 delivered story/emotion -> Team3 imagery -> DreamModel',
            'upstream_programs_rerun':False,'validated_scenes':len(bundle.scenes),
            'rendered_scenes':[s.scene_id for s in bundle.scenes[:2]],
            'story_plans':[p.as_report() for p in plans[:2]],
            'actual_audience_aggregate_supplied':config.audience.source!='preview defaults; no measured audience aggregate supplied'},
        'law_map':events.report(),'evolution':world.search.report(),
        'inheritance':world.inheritance,'audience':config.audience.report(),
        'audio':{**audio.as_report(),'timeline':timing},
        'samples':samples,'raw_frames_sha256':digest.hexdigest(),
        'frame_change':{'mean_rgb_absolute_delta':float(np.mean(deltas)),
                        'maximum_rgb_absolute_delta':float(max(deltas))},
        'input_files':[{'path':str(p),'sha256':file_digest(p)} for p in dict.fromkeys([*bundle.input_files,*memories.sources])],
        'code_files':[{'path':str(p),'sha256':file_digest(p)} for p in (
            Path(__file__),Path(__file__).with_name('developmental_world.py'),
            Path(__file__).with_name('developmental_renderer.py'),Path(__file__).with_name('story_events.py'),
            Path(__file__).with_name('frame_renderer.py'),Path(__file__).with_name('input_loader.py'),
            Path(__file__).with_name('audio_analyzer.py'),Path(__file__).with_name('semantic_conditioning.py'),
            config.semantic_config)],
        'scope':{
            'background':'source-textured regional development, perspective deformation, persistent motion-biased transition field',
            'objects':'source-textured connected surfaces; root-out growth, curved page, structural sheet/fold variants',
            'search':'typed mutation/recombination, cooperative proxy fitness, morphology-cell archive',
            'placement':'artistic 2.5D approximation; source assets have no camera/depth/layout metadata',
            'audio_space_law':'energy/onset envelope proxy; not a detected sequence of individual water-drop sounds',
            'not_claimed':['learned 3D reconstruction','unbounded open-endedness','complete four-scene event rendering','audience-validated visual success']},
        'elapsed_seconds':time.perf_counter()-started}
    config.report_path.parent.mkdir(parents=True,exist_ok=True)
    config.report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    contact=Image.new('RGB',(config.width*len(captured),config.height))
    for i,(_,im) in enumerate(captured):contact.paste(im,(config.width*i,0))
    contact.save(config.output_path.with_name(config.output_path.stem+'_contact.jpg'),quality=92)
    print(f'[complete] {config.output_path}',flush=True)
    return report
