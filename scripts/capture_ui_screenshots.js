const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const USER_DATA = path.join(__dirname, '..', '.edge_profile');

async function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function sendCdp(ws, method, params = {}) {
  const id = Math.floor(Math.random() * 1000000);
  return new Promise((resolve, reject) => {
    const handler = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.id === id) {
          ws.removeEventListener('message', handler);
          resolve(msg.result);
        }
      } catch (e) {
        reject(e);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function main() {
  const shotDir = path.join(__dirname, '..', 'docs', 'screenshots');
  if (!fs.existsSync(shotDir)) fs.mkdirSync(shotDir, { recursive: true });

  console.log('1. Spawning Edge in headless mode with debugging port 9222...');
  const edge = spawn(EDGE_PATH, [
    '--headless=new',
    '--remote-debugging-port=9222',
    '--disable-gpu',
    `--user-data-dir=${USER_DATA}`,
    'http://localhost:5173/'
  ]);

  let connected = false;
  let target = null;
  for (let i = 0; i < 20; i++) {
    await sleep(500);
    try {
      const list = await getJson('http://127.0.0.1:9222/json/list');
      target = list.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
      if (target) {
        connected = true;
        break;
      }
    } catch (e) {
      // Waiting for port
    }
  }

  if (!connected || !target) {
    throw new Error('Failed to connect to Edge CDP target.');
  }

  console.log('2. Connected to target WebSocket:', target.webSocketDebuggerUrl);
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);

  await sendCdp(ws, 'Page.enable');
  await sendCdp(ws, 'Runtime.enable');
  await sendCdp(ws, 'Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false
  });

  await sleep(1500);

  // A. Clear session to guarantee clean Login Page capture
  console.log('Clearing localStorage to capture real Login Page...');
  await sendCdp(ws, 'Runtime.evaluate', {
    expression: `localStorage.clear(); location.reload();`,
    returnByValue: true
  });
  await sleep(2500);

  console.log('Capturing 01_login_page.png...');
  let shot = await sendCdp(ws, 'Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(shotDir, '01_login_page.png'), Buffer.from(shot.data, 'base64'));

  // B. Submit Login Form
  console.log('Submitting login form in UI...');
  const loginEval = await sendCdp(ws, 'Runtime.evaluate', {
    expression: `
      (() => {
        const btn = document.querySelector('button[type="submit"]');
        if (btn) {
          btn.click();
          return 'Clicked submit button';
        }
        return 'No submit button';
      })()
    `,
    returnByValue: true
  });
  console.log('Login action result:', loginEval && loginEval.result ? loginEval.result.value : 'done');

  // Wait for login to complete and dashboard to load
  await sleep(4000);

  // Helper to click sidebar tab and capture
  async function captureTab(tabText, filename) {
    console.log(`Navigating to ${tabText}...`);
    const clickRes = await sendCdp(ws, 'Runtime.evaluate', {
      expression: `
        (() => {
          const els = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
          const targetEl = els.find(e => e.innerText && e.innerText.trim().includes('${tabText}'));
          if (targetEl) {
            targetEl.click();
            return 'Clicked ' + targetEl.innerText.trim();
          }
          return 'Not found';
        })()
      `,
      returnByValue: true
    });
    console.log(`Click result for ${tabText}:`, clickRes && clickRes.result ? clickRes.result.value : 'done');
    await sleep(3000);
    console.log(`Capturing ${filename}...`);
    const s = await sendCdp(ws, 'Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(shotDir, filename), Buffer.from(s.data, 'base64'));
  }

  // Capture Overview
  console.log('Capturing 02_overview_dashboard.png...');
  shot = await sendCdp(ws, 'Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(shotDir, '02_overview_dashboard.png'), Buffer.from(shot.data, 'base64'));

  await captureTab('Live Detection', '03_live_detection.png');
  await captureTab('Alerts & Triage', '04_alerts_page.png');
  await captureTab('Model Performance', '05_model_performance.png');
  await captureTab('Traffic Analysis', '06_traffic_analysis.png');
  await captureTab('Monitoring & Drift', '07_monitoring.png');

  ws.close();
  edge.kill();
  console.log('Done! All 7 authentic screenshots captured.');
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
