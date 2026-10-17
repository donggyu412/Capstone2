// 헤드리스 크롬(CDP)으로 [영상 mp4 · 프레임 고정] 한 바퀴를 기록한다. 같은 바퀴에서 [장면 저장](배경판 PNG)도 같이 찍는다.
// 사용: python team3/run_team3.py --record (서버 · 크롬을 띄우고 이 파일을 부른다)
//       직접: node record.mjs <cdpPort> <url>   결과는 서버의 output/<시각>_storyboard_mp4/ · output/<시각>_storyboard/
// (10-11 output/20261011_tone_test/_촬영도구/ 에서 옮김 · 10-17)
const [port, url] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));

const tab = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const wait = new Map(); const errors = [];
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && wait.has(m.id)) { wait.get(m.id)(m.result || m.error); wait.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map(a => a.value || a.description).join(' '));
});
const send = (method, params = {}) => new Promise(r => { wait.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });
const ev = async e => (await send('Runtime.evaluate', { expression: e, returnByValue: true })).result?.value;
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a);

await send('Runtime.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url });
await sleep(3000);
await send('Runtime.evaluate', { expression: 'startSim();', userGesture: true });
for (let k = 0; k < 120; k++) { if (await ev('scenes.length > 0 && sceneIdx >= 0')) break; await sleep(250); }
log('판', await ev('W + "x" + H'), '· 장면', await ev('scenes.length'), '· 장면당', await ev('SCENE_SEC'), '초 · 감정', await ev('JSON.stringify(scenes.map(s => s.emotion))'));

// 장면 저장을 같이 건다 — togglePngSave 와 같은 준비(한 바퀴 출발은 영상 쪽 startCycle 이 한다)
await ev(`exportArmed = true; exportDone = {}; exportRun = stamp() + '_' + ((SRC_INFO && SRC_INFO.mode) || 'input'); toggleFixRec(false); 1`);
log('기록 폴더', await ev('fix && fix.run'), '· 배경판 폴더', await ev('exportRun'));

const t0 = Date.now(); let last = 0, lastN = 0, lastT = t0, stall = 0;
for (;;) {
  await sleep(5000);
  const s = JSON.parse(await ev(`JSON.stringify(fix ? { st: fix.state, n: fix.n, total: fix.total, codec: fix.codec, err: fix.err ? String(fix.err.message || fix.err) : null, sc: sceneIdx, png: Object.keys(exportDone).length } : { done: true, png: Object.keys(exportDone).length, msg: document.getElementById('g-exp').textContent })`) || '{"lost":true}');
  if (s.lost) { log('페이지 응답 없음'); if (++stall > 12) break; continue; }
  if (s.done) { log('끝 —', s.msg, '· 배경판', s.png + '장', '· 걸린 시간', ((Date.now() - t0) / 60000).toFixed(1) + '분'); break; }
  stall = s.n === lastN ? stall + 1 : 0;
  if (stall > 60) { log('5분 동안 프레임이 늘지 않음 — 중단', JSON.stringify(s)); break; }
  if (Date.now() - last > 60000) {
    const fps = (s.n - lastN) / ((Date.now() - lastT) / 1000);
    log(s.st, (s.n / s.total * 100).toFixed(1) + '%', '장면', s.sc + 1, '· 엔진', fps.toFixed(1), 'fps ·', s.codec || '', '· 배경판', s.png, s.err ? '· 오류 ' + s.err : '');
    last = Date.now(); lastN = s.n; lastT = Date.now();
  } else if (s.n !== lastN && last === 0) { lastN = s.n; lastT = Date.now(); }
}
log('JS 오류:', errors.length ? errors.slice(0, 5) : '없음');
await sleep(3000);          // 마지막 배경판 전송이 끝나길 잠깐 기다린다
await send('Page.close'); ws.close();
