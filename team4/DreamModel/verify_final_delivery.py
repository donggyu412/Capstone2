"""Verify the delivered 300-second MP4 and save images decoded from that file.

Run after rendering has completed. This checks media integrity/provenance, not
whether the artistic result satisfies the viewer. It never modifies the video.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

try:
    from .audio_analyzer import AudioAnalyzer
    from .frame_renderer import find_ffmpeg, subprocess_options
    from .run_report import file_digest
except ImportError:
    # Support direct invocation as well as python -m team4.DreamModel....
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from team4.DreamModel.audio_analyzer import AudioAnalyzer
    from team4.DreamModel.frame_renderer import find_ffmpeg, subprocess_options
    from team4.DreamModel.run_report import file_digest


FPS, FRAMES, SECONDS = 30, 9000, 300
SIZE = [1920, 1080]
REPO = Path(__file__).resolve().parents[2]
DEFAULT_VIDEO = REPO / 'team4/DreamModel/output/final_delivery/Collective_Dreaming_Final_1080p_300s.mp4'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def resolve_report_path(value, report_path):
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    for root in (REPO, report_path.parent):
        if (root / candidate).exists():
            return (root / candidate).resolve()
    return (REPO / candidate).resolve()


def mp4_atoms(path):
    """Read top-level atom headers, without loading a large movie into memory."""
    result = []
    length = path.stat().st_size
    with path.open('rb') as stream:
        while stream.tell() + 8 <= length:
            offset = stream.tell()
            size, kind = struct.unpack('>I4s', stream.read(8))
            header_size = 8
            if size == 1:
                require(offset + 16 <= length, 'Truncated extended MP4 atom header')
                size = struct.unpack('>Q', stream.read(8))[0]
                header_size = 16
            elif size == 0:
                size = length - offset
            require(header_size <= size <= length - offset, 'Invalid MP4 atom length')
            result.append({'type': kind.decode('ascii', errors='replace'), 'offset': offset, 'bytes': size})
            stream.seek(offset + size)
    return result


def contact_sheet(path, rows, samples, columns=4, width=480):
    height = round(width * 9 / 16)
    cell_height = height + 30
    sheet = Image.new('RGB', (columns * width, math.ceil(len(rows) / columns) * cell_height), (13, 17, 21))
    draw = ImageDraw.Draw(sheet)
    for index, (frame, label) in enumerate(rows):
        image = samples[frame]
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        x, y = index % columns * width, index // columns * cell_height
        sheet.paste(image, (x, y))
        draw.text((x + 6, y + height + 7), f'{frame/FPS:07.3f}s  |  {label}', fill='white')
    sheet.save(path, quality=95, subsampling=0)


def strict_decode(video, notify):
    """FFmpeg reports damaged streams that an accommodating player may conceal."""
    command = [find_ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error',
               '-xerror', '-err_detect', 'explode', '-threads', '2', '-i', str(video),
               '-map', '0:v:0', '-map', '0:a:0', '-progress', 'pipe:1',
               '-stats_period', '5', '-nostats', '-f', 'null', '-']
    progress = {}
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                   text=True, encoding='utf-8', errors='replace', **subprocess_options())
        try:
            for line in process.stdout:
                key, separator, value = line.strip().partition('=')
                if separator:
                    progress[key] = value
                if key == 'progress':
                    notify('strict_decode', frames=int(progress.get('frame', '0')),
                           out_time=progress.get('out_time'), progress=value)
            returncode = process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
            process.stdout.close()
        errors.seek(0)
        diagnostic = errors.read().decode('utf-8', errors='replace').strip()
    require(returncode == 0, f'Strict FFmpeg decode failed: {diagnostic[-4000:]}')
    require(int(progress.get('frame', '0')) == FRAMES, f'FFmpeg decoded {progress.get("frame")} frames')
    return {'passed': True, 'decoded_frames': int(progress['frame']), 'diagnostic': diagnostic,
            'checks': 'H.264 and AAC fully decoded with -xerror -err_detect explode'}


def verify(video, report_path, audio_override=None, protected_path=None, output_dir=None):
    started = time.perf_counter()
    video, report_path = video.resolve(), report_path.resolve()
    folder = (output_dir or video.parent).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    status_path = folder / 'final_verification_status.json'
    result_path = folder / 'final_media_validation.json'
    result = {'passed': False, 'video': str(video), 'render_report': str(report_path),
              'scope': 'Actual final MP4 media integrity, decoded contact frames, and listed-file provenance; artistic approval is separate.'}

    def notify(stage, **values):
        status = {'stage': stage, 'elapsed_seconds': round(time.perf_counter()-started, 1), **values}
        save_json(status_path, status)
        print('[final verification]', json.dumps(status, ensure_ascii=False), flush=True)

    try:
        notify('opening')
        require(video.is_file(), f'Final video does not exist: {video}')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        require(report.get('resolution') == SIZE and report.get('fps') == FPS, 'Render report has the wrong resolution/fps')
        require(report.get('frames') == FRAMES and report.get('duration_seconds') == SECONDS, 'Render report is not a 300-second final render')
        require(report.get('scene_seconds') == 75 and report.get('nominal_scene_starts') == [0,75,150,225], 'Render report is not four 75-second scenes')
        require(resolve_report_path(report['output_file'], report_path) == video, 'Report output_file does not identify this MP4')
        atoms = mp4_atoms(video)
        types = [atom['type'] for atom in atoms]
        require('moov' in types and 'mdat' in types, 'MP4 is missing moov/mdat')
        require(types.index('moov') < types.index('mdat'), 'MP4 does not have faststart metadata before media data')
        probe = subprocess.run([find_ffmpeg(), '-nostdin', '-hide_banner', '-i', str(video)],
                               capture_output=True, **subprocess_options())
        streams = probe.stderr.decode('utf-8', errors='replace')
        (folder / 'final_stream_probe.txt').write_text(streams, encoding='utf-8')
        require('Video: h264' in streams and 'Audio: aac' in streams, 'MP4 must contain H.264 video and AAC audio')
        require('yuv420p' in streams, 'Final MP4 must use broadly playable yuv420p pixels')
        duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', streams)
        require(duration_match is not None, 'Cannot inspect container duration')
        container_duration = sum(float(value)*factor for value,factor in zip(duration_match.groups(), (3600,60,1)))
        require(abs(container_duration - SECONDS) <= .1, f'Unexpected container duration: {container_duration}')
        start_match = re.search(r'start:\s*(-?\d+(?:\.\d+)?)', streams)
        require(start_match is not None and abs(float(start_match.group(1))) <= 1/FPS, 'Unexpected container start time')
        result['container'] = {'duration_seconds': container_duration, 'video_codec': 'h264', 'audio_codec': 'aac',
                               'pixel_format': 'yuv420p', 'faststart': True, 'top_level_atoms': atoms}

        overview = [(round(t*FPS), f'scene {min(4,int(t//75)+1)}')
                    for t in (0,5,10,20,40,65,75,90,110,135,150,165,185,210,225,240,260,280,295,299+29/30)]
        transitions = [(min(FRAMES-1,round(t*FPS)), f'transition {index+1}->{index+2}')
                       for index, boundary in enumerate((75,150,225))
                       for t in (boundary-10,boundary-5,boundary-1,boundary-1/FPS,boundary,boundary+1/FPS,boundary+5,boundary+15)]
        formation = [(round(t*FPS), 'initial formation') for t in (0,2,5,8,12,16,20,30)]
        dissolution = [(min(FRAMES-1,round(t*FPS)), 'final scene / dissolution')
                       for t in (250,260,270,280,290,295,299,299+29/30)]
        wanted = {frame for frame,_ in overview+transitions+formation+dissolution}
        samples, changes, visual_samples = {}, [], []
        cap = cv2.VideoCapture(str(video))
        require(cap.isOpened(), 'OpenCV cannot open final MP4')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        size = [int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))]
        declared = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        require(size == SIZE and abs(fps-FPS) < 1e-6 and declared == FRAMES, f'Unexpected video metadata: {size}, {fps} fps, {declared} frames')
        cv2.setNumThreads(1)
        count, previous, last_notice = 0, None, time.perf_counter()
        try:
            while True:
                okay, pixels = cap.read()
                if not okay:
                    break
                require(list(pixels.shape[:2]) == [1080,1920], f'Invalid decoded frame dimensions at {count}')
                thumbnail = cv2.resize(pixels, (160,90), interpolation=cv2.INTER_AREA).astype(np.float32)
                if previous is not None:
                    changes.append(float(np.mean(np.abs(thumbnail-previous))))
                previous = thumbnail
                if count in wanted:
                    small = cv2.resize(pixels, (480,270), interpolation=cv2.INTER_AREA)
                    samples[count] = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
                    visual_samples.append({'frame': count, 'seconds': count/FPS, 'mean_rgb_level': float(thumbnail.mean()),
                                           'spatial_std': float(thumbnail.std(axis=(0,1)).mean())})
                count += 1
                if time.perf_counter()-last_notice >= 10 or count == FRAMES:
                    notify('full_frame_decode', frames=count, expected_frames=FRAMES, percent=round(100*count/FRAMES,1))
                    last_notice = time.perf_counter()
        finally:
            cap.release()
        require(count == FRAMES, f'Only {count}/{FRAMES} frames decoded')
        require(wanted.issubset(samples), 'Requested actual decoded contact frames are missing')
        deltas = np.asarray(changes)
        boundary_changes = [{'time_seconds': boundary, 'frame': boundary*FPS, 'difference': changes[boundary*FPS-1],
                             'neighbourhood_mean': float(deltas[boundary*FPS-16:boundary*FPS+14].mean())}
                            for boundary in (75,150,225)]
        top_changes = [{'frame': int(index+1), 'time_seconds': (int(index)+1)/FPS, 'difference': float(deltas[index])}
                       for index in np.argsort(deltas)[-12:][::-1]]
        result['video_decode'] = {'decoded_frames': count, 'declared_frames': declared, 'resolution': size, 'fps': fps,
            'duration_seconds': count/fps, 'frame_change_mean': float(deltas.mean()), 'frame_change_p99': float(np.percentile(deltas,99)),
            'largest_frame_changes': top_changes, 'scene_boundaries': boundary_changes, 'sample_statistics': visual_samples,
            'caveat': 'Frame-change statistics describe continuity; they do not certify natural motion or readable object identity.'}
        contacts = {}
        for name, rows in [('final_decoded_contact',overview), ('final_transitions_decoded_contact',transitions),
                           ('final_formation_decoded_contact',formation), ('final_dissolution_decoded_contact',dissolution)]:
            path = folder / (name+'.jpg')
            contact_sheet(path, rows, samples)
            contacts[name] = str(path)
        result['decoded_contacts'] = contacts
        notify('contacts_saved', files=contacts)
        result['strict_decode'] = strict_decode(video, notify)

        notify('audio_sync')
        source_audio = audio_override or report.get('audio',{}).get('path')
        require(source_audio is not None, 'Original source WAV must be supplied or named in report.audio.path')
        source_audio = resolve_report_path(source_audio, report_path)
        baseline, delivered = AudioAnalyzer(source_audio), AudioAnalyzer(video)
        require(baseline.duration >= SECONDS-1/FPS, 'Provided original audio is shorter than 300 seconds')
        require(abs(delivered.duration-SECONDS) <= .1, f'Final decoded audio duration is {delivered.duration}')
        ts = np.arange(.5, SECONDS-.5, .05)
        reference = np.interp(ts, baseline.times, baseline.values)
        envelope = np.interp(ts, delivered.times, delivered.values)
        require(float(reference.std()) > 1e-7 and float(envelope.std()) > 1e-7, 'Cannot verify soundtrack synchronization from an invariant/silent envelope')
        correlation = float(np.corrcoef(reference,envelope)[0,1])
        require(correlation > .995, f'Audio envelope correlation is too low: {correlation}')
        lags = {round(float(lag),3): float(np.corrcoef(reference,np.interp(ts+lag,delivered.times,delivered.values))[0,1])
                for lag in np.arange(-.25,.251,.025)}
        best_lag = max(lags, key=lags.get)
        require(abs(best_lag) <= .05, f'Soundtrack best alignment has {best_lag}s lag')
        section_correlations = []
        for start in (0,75,150,225):
            mask = (ts>=start+.5)&(ts<start+74.5)
            value = float(np.corrcoef(reference[mask],envelope[mask])[0,1])
            require(value > .995, f'Scene {start//75+1} soundtrack correlation is {value}')
            section_correlations.append({'start_seconds': start, 'end_seconds': start+75, 'correlation': value})
        result['audio'] = {'source': str(source_audio), 'source_seconds': baseline.duration, 'decoded_seconds': delivered.duration,
            'envelope_correlation': correlation, 'best_lag_seconds': best_lag, 'lag_correlations': lags,
            'per_scene_correlations': section_correlations, 'source_sha256': file_digest(source_audio),
            'caveat': 'AAC is lossy; synchronization is checked by full-duration smoothed amplitude envelopes, not byte equality.'}
        notify('provenance')
        for key in ('input_files','code_files'):
            records = report.get(key,[])
            require(bool(records), f'Render report has no {key} provenance list')
            checked = []
            for record in records:
                path = resolve_report_path(record['path'],report_path)
                actual = file_digest(path) if path.is_file() else None
                checked.append({'path': str(path), 'expected_sha256': record['sha256'], 'actual_sha256': actual, 'matches': actual == record['sha256']})
            result[key] = checked
            require(all(row['matches'] for row in checked), f'Changed or missing {key}: {[row["path"] for row in checked if not row["matches"]]}')
        required_code = {'background_openended.py','dream_world.py','dream_surfaces.py','dream_score.py'}
        require(required_code.issubset({Path(row['path']).name for row in result['code_files']}), 'Render report omits a core new engine from its code hash list')
        protected_path = protected_path or REPO.parent.parent/'work/formation-review/protected_before.json'
        protected = json.loads(protected_path.read_text(encoding='utf-8'))
        changed = [name for name,expected in protected.items() if not (REPO/name).is_file() or file_digest(REPO/name) != expected]
        result['protected_files'] = {'manifest': str(protected_path), 'checked': len(protected), 'changed': changed}
        require(not changed, f'Protected files changed: {changed}')
        result.update({'passed': True, 'bytes': video.stat().st_size, 'sha256': file_digest(video),
                       'listed_input_hashes_match': True, 'listed_code_hashes_match': True,
                       'elapsed_seconds': round(time.perf_counter()-started,2)})
        save_json(result_path,result)
        notify('complete', passed=True, validation=str(result_path), frames=FRAMES, seconds=SECONDS,
               audio_correlation=correlation, bytes=result['bytes'])
        return result
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['elapsed_seconds'] = round(time.perf_counter()-started,2)
        save_json(result_path,result)
        notify('failed', error=result['error'], validation=str(result_path))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path, nargs='?', default=DEFAULT_VIDEO)
    parser.add_argument('--report', type=Path, help='Default: VIDEO_STEM_run_report.json beside the MP4')
    parser.add_argument('--audio', type=Path, help='Original received WAV; otherwise read report.audio.path')
    parser.add_argument('--protected', type=Path, help='Override protected_before.json manifest')
    parser.add_argument('--output-dir', type=Path, help='Directory for validation/contact sheets; default beside MP4')
    args = parser.parse_args()
    report_path = args.report or args.video.with_name(args.video.stem+'_run_report.json')
    verify(args.video, report_path, args.audio, args.protected, args.output_dir)
