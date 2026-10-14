"""Empty-state formation proof, original 0-20 seconds; no complete image plates."""
import hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from PIL import Image
from .config import REPO_ROOT
from .developmental_pipeline import prepare
from .emergence_renderer import EmergenceRenderer
from .audio_analyzer import AudioAnalyzer
from .painterly_pipeline import prepare_audio
from .frame_renderer import VideoWriter
from .run_report import file_digest


def render(config,audio_path=None):
    if not config.smoke:raise ValueError('This is a formation preview only; --final is disabled.')
    if (config.preview_start_seconds,config.preview_seconds,config.scene_seconds)!=(0,20,75):
        raise ValueError('Formation proof requires original 0-20 seconds and a 75-second scene clock.')
    cv2.setNumThreads(1);started=time.perf_counter()
    bundle,plans,memories,events,world,_=prepare(config,audio_path)
    surface=EmergenceRenderer(bundle,plans,config.width,config.height,config.seed)
    audio=AudioAnalyzer(bundle.audio_path)
    clip,timing=prepare_audio(bundle.audio_path,config.output_path.with_name(config.output_path.stem+'_audio.wav'),0,20)
    samples=[];frames=[];deltas=[];previous=None;digest=hashlib.sha256()
    code_paths=[Path(__file__),Path(__file__).with_name('emergence_renderer.py'),
                Path(__file__).with_name('developmental_world.py'),Path(__file__).with_name('input_loader.py')]
    code_hashes=[{'path':str(p),'sha256':file_digest(p)} for p in code_paths]
    with VideoWriter(config.output_path,config.width,config.height,30,audio_path=clip,
            expected_frames=600,crf=18,keyframe_interval=600) as writer:
        for frame in range(600):
            t=frame/30
            world.step(t,1/30,*audio.features(t))
            pixels=surface.render(world)
            if frame==0:
                assert sum(surface.stats['surface_area_pixels'].values())==0
                assert np.ptp(pixels,axis=(0,1)).max()==0
            writer.write(pixels);digest.update(pixels.tobytes())
            if previous is not None:deltas.append(float(np.abs(pixels.astype(float)-previous).mean()))
            previous=pixels.astype(float)
            if frame%30==0 or frame==599:samples.append({**world.snapshot(),'renderer':surface.stats.copy()})
            if frame in (0,120,240,360,480,599):frames.append(Image.fromarray(pixels))
            if frame%150==0:print(f'[formation] {t:.0f}/20 seconds',flush=True)
    report={'model':'DreamModel constructive emergence proof',
        'scope':'Only original 0-20s to inspect birth from absence; transition acceptance remains outstanding.',
        'resolution':[config.width,config.height],'fps':30,'frames':600,'duration':20,
        'source_window':[0,20],'playback_rate':1.,'original_scene_seconds':75,
        'first_frame':'empty material field; no background or object surface',
        'method':'source contour/adjacency/colour features -> growing and merging geometric surfaces; no full source plate/sprite compositing',
        'bounded_method':world.search.report(),'seed':config.seed,'samples':samples,
        'audio':{**audio.as_report(),'timeline':timing},'audience':config.audience.report(),
        'validated_scenes':4,'rendered_scenes':[1],
        'law_scope':'Story order and condition inputs are active; late story events do not occur in original 0-20s.',
        'input_files':[{'path':str(p),'sha256':file_digest(p)} for p in dict.fromkeys([*bundle.input_files,*memories.sources])],
        'code_files':code_hashes,'frame_change':{'mean':float(np.mean(deltas)),'maximum':float(max(deltas))},
        'raw_frames_sha256':digest.hexdigest(),'elapsed_seconds':time.perf_counter()-started,
        'limitations':['finite source-conditioned regional geometry, not unrestricted OEE',
                       'visual readability and shared-scene coherence require review; no automatic acceptance',
                       'two-scene transition not included in this birth proof']}
    config.report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    contact=Image.new('RGB',(config.width*3,config.height*2))
    for i,im in enumerate(frames):contact.paste(im,((i%3)*config.width,(i//3)*config.height))
    contact.save(config.output_path.with_name(config.output_path.stem+'_contact.jpg'),quality=93)
    print(f'[complete] {config.output_path}',flush=True)
    return report
