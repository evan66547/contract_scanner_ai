/**
 * 合同扫描器 - AI增强版
 * OCR引擎: GLM-OCR via Ollama (本地AI)
 */

// 全局状态
let targets = [];
let targetCharWeights = null;
const STATE = { SCANNING: 'scanning', MATCHED: 'matched', NOT_MATCHED: 'not-matched' };

let isScanning = true;
let shouldAutoScan = false;
let scanInterval = null;
let consecutiveMatches = 0;
let lastMatchedTarget = null;
let isProcessing = false;
let processingTimeout = null;
let matchDismissTimer = null;
let lastScanTime = 0;
let frameCount = 0;
let config = {};
const DEFAULT_CONFIG = {
  scan: { width: 640, height: 480, frameRate: 30 },
  roi: { x: 5, y: 5, width: 90, height: 12 },
  matching: {
    minConfidence: 0,
    levenshteinDistance: null,
    minMatchRatio: 0.6,
    requirePrefix: true,
    minKeywordLength: 5
  },
  ui: { showDebug: true, showOverlay: true },
  ocr: {
    provider: 'paddle',
    paddle: {
      useGpu: false,
      ocrVersion: 'PP-OCRv6',
      textDetectionModelName: 'PP-OCRv6_tiny_det',
      textRecognitionModelName: 'PP-OCRv6_tiny_rec'
    }
  }
};
let adbWifiIp = null;
let adbStepStates = [1, 0, 0, 0, 0]; // 0=默认, 1=active, 2=done
let ws = null;
let isWsConnected = false;
let wsReconnectAttempts = 0;
const WS_MAX_RECONNECT = 10;
const WS_BASE_DELAY = 1000;
const OCR_RESPONSE_TIMEOUT_MS = 65000;

// 每日扫描计数
let dailyScanCount = 0;
let totalScanCount = 0;
let lastScanDate = '';
let scanStatsPollTimer = null;
const SCAN_STATS_POLL_MS = 2000;
const DEVICE_ID_KEY = 'scannerDeviceId';
const DEVICE_LABEL_KEY = 'scannerDeviceLabel';

// 连接模式
let networkInfo = null;
let currentConnMode = 'usb'; // auto-detected

// DOM元素
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d', { willReadFrequently: true });
const overlay = document.getElementById('overlay');
const statusIcon = document.getElementById('status-icon');
const statusText = document.getElementById('status-text');
const matchedTargetEl = document.getElementById('matched-target');
const debugEl = document.getElementById('debug');
const toggleBtn = document.getElementById('toggle-btn');
const scanRegionEl = document.querySelector('.scan-region');
const scanCounterTotalValEl = document.getElementById('scan-counter-total-val');
const scanCounterLocalValEl = document.getElementById('scan-counter-local-val');
const scanCountMinusBtn = document.getElementById('scan-count-minus');
const scanCountPlusBtn = document.getElementById('scan-count-plus');

// SVG 图标映射（替换 emoji，保证跨平台渲染一致）
const ICONS = {
  '⚡️': '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
  '✅': '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  '❌': '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
  '⏸': '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>',
  '▶': '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
};

// 初始化
async function init() {
  log('🚀 开始初始化...');
  initDailyCounter();

  // 检查安全上下文
  if (!window.isSecureContext) {
    console.warn('当前不是安全上下文');
    log('❌ 警告: 当前不是安全上下文(HTTPS/localhost)');
    log('无法访问摄像头');
  } else {
    log('✅ 安全上下文: 是');
  }

  const hasCameraApi = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  if (!hasCameraApi) {
    log('❌ 错误: 浏览器不支持 mediaDevices.getUserMedia');
  }

  try {

    log('1. 正在加载配置...');
    await loadConfig();
    log('✅ 配置加载成功');

    log('2. ' + t('msg.loading_list', 'Loading target list...'));
    await loadCompanies();
    await loadTargetHeaders();
    log('✅ ' + t('msg.loaded', 'Target list loaded successfully'));

    log('3. 检测连接模式...');
    await loadNetworkInfo();
    currentConnMode = 'usb';
    updateConnPanelUI();

    statusText.textContent = '准备就绪';
    const startBtn = document.getElementById('start-btn');
    startBtn.style.display = 'block';

    // 非安全上下文（直接 IP 访问）= iOS Safari 会阻止摄像头
    const isSecure = window.isSecureContext;
    if (!hasCameraApi) {
      statusText.textContent = '当前浏览器无法调用摄像头';
      matchedTargetEl.textContent = '请使用 Android Chrome；iPhone/Safari 需要通过管理台里的 Tailscale HTTPS 地址访问。';
      startBtn.disabled = true;
      startBtn.style.opacity = '0.6';
      startBtn.style.cursor = 'not-allowed';
    }
    if (!isSecure) {
      log('⚠️ 当前为非安全上下文，getUserMedia 可能被阻止');
      statusText.textContent = 'HTTP 访问可能被浏览器拦截摄像头';
      matchedTargetEl.textContent = 'Android Chrome 可在 flags 中信任当前地址；iPhone/Safari 必须使用 Tailscale HTTPS。';
    }

    // 检查是否带有 autostart 参数（从管理面板远程启动）
    const urlParams = new URLSearchParams(window.location.search);
    const autoStart = urlParams.get('autostart') === '1';

    startBtn.onclick = async () => {
      startBtn.style.display = 'none';
      log('🚀 用户点击启动...');

      // 强制显示调试面板，方便排查问题
      debugEl.classList.add('visible');

      try {
        log('3. 初始化摄像头...');
        await initCamera();
        log('✅ 摄像头就绪 (' + canvas.width + 'x' + canvas.height + ')');

        // 初始化 WebSocket
        log('4. 初始化 WebSocket 引擎...');
        await initWebSocket();
        log('✅ WS 就绪, isScanning=' + isScanning + ', scanInterval=' + !!scanInterval);

        applyConfigToUI();
        startScanning();
        log('✅ 扫描已启动, scanInterval=' + !!scanInterval);
        bindEvents();
      } catch (e) {
        log('❌ 启动失败: ' + e.message);
        if (!isSecure && (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError' || e.message.includes('secure context'))) {
          updateStatus(STATE.NOT_MATCHED, '❌', '启动失败：安全上下文限制',
            '当前浏览器限制了非 localhost 的摄像头权限。\n\n' +
            'Android Chrome: 打开 chrome://flags/#unsafely-treat-insecure-origin-as-secure，填入 ' + window.location.origin + ' 并重启 Chrome。\n\n' +
            'iPhone/Safari: 必须使用管理台里的 Tailscale HTTPS 地址。\n\n' +
            'USB/ADB: 可继续使用 localhost:8093。');
        } else {
          updateStatus(STATE.NOT_MATCHED, '❌', '启动失败', e.message);
        }
      }
    };

    // 如果带了 autostart 参数，自动触发启动
    if (autoStart && window.isSecureContext && navigator.mediaDevices) {
      log('🤖 检测到自动启动参数，正在自动启动...');
      startBtn.click();
    }

  } catch (error) {
    log('❌ 初始化失败: ' + error.message);

    // 针对摄像头权限的特殊提示
    if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
      updateStatus(STATE.NOT_MATCHED, '🚫', '需要摄像头权限', '请在浏览器设置中允许访问摄像头\n\n刷新页面重试');
    } else if (error.name === 'NotFoundError') {
      updateStatus(STATE.NOT_MATCHED, '📷', '未找到摄像头', '请确保设备有可用的摄像头');
    } else {
      updateStatus(STATE.NOT_MATCHED, '❌', '系统错误', error.message);
    }
  }
}

function createDeviceId() {
  const randomPart = Math.random().toString(36).slice(2, 10);
  const timePart = Date.now().toString(36);
  return 'dev-' + timePart + '-' + randomPart;
}

function detectDeviceLabel() {
  const ua = navigator.userAgent || '';
  if (/iPhone/i.test(ua)) return 'iPhone';
  if (/iPad/i.test(ua)) return 'iPad';
  const androidModel = ua.match(/Android[^;]*;\s*([^;)]+)\s+Build\/[^;)]+/i);
  if (androidModel && androidModel[1]) {
    const model = androidModel[1]
      .replace(/\bwv\b/ig, '')
      .replace(/\bMobile\b/ig, '')
      .trim();
    if (model && model.length > 1 && !/^[A-Z]$/i.test(model)) {
      return model.slice(0, 32);
    }
  }
  if (/Android/i.test(ua)) return 'Android 手机';
  return navigator.platform || '手机设备';
}

function getScannerDeviceInfo() {
  let deviceId = localStorage.getItem(DEVICE_ID_KEY);
  if (!deviceId) {
    deviceId = createDeviceId();
    localStorage.setItem(DEVICE_ID_KEY, deviceId);
  }
  let label = localStorage.getItem(DEVICE_LABEL_KEY);
  if (!label) {
    label = detectDeviceLabel();
    localStorage.setItem(DEVICE_LABEL_KEY, label);
  }
  return { deviceId, label };
}

// 加载配置
async function loadConfig() {
  log('⚙️ 加载配置...');
  const res = await fetch('/api/config?t=' + Date.now());
  const loadedConfig = await res.json();
  config = {
    ...DEFAULT_CONFIG,
    ...loadedConfig,
    scan: { ...DEFAULT_CONFIG.scan, ...(loadedConfig.scan || {}) },
    roi: { ...DEFAULT_CONFIG.roi, ...(loadedConfig.roi || {}) },
    matching: { ...DEFAULT_CONFIG.matching, ...(loadedConfig.matching || {}) },
    ui: { ...DEFAULT_CONFIG.ui, ...(loadedConfig.ui || {}) },
    ocr: {
      ...DEFAULT_CONFIG.ocr,
      ...(loadedConfig.ocr || {}),
      paddle: {
        ...DEFAULT_CONFIG.ocr.paddle,
        ...((loadedConfig.ocr && loadedConfig.ocr.paddle) || {})
      }
    }
  };
  log('✅ 配置已加载');
}

// 应用配置到UI
function applyConfigToUI() {
  // 更新扫描框样式
  if (scanRegionEl) {
    scanRegionEl.style.left = `${config.roi.x}%`;
    scanRegionEl.style.top = `${config.roi.y}%`;
    scanRegionEl.style.width = `${config.roi.width}%`;
    scanRegionEl.style.height = `${config.roi.height}%`;
  }

  // 调试显示
  if (config.ui.showDebug) debugEl.classList.add('visible');

  // 覆盖层
  if (!config.ui.showOverlay) {
    if (document.querySelector('.scan-line')) document.querySelector('.scan-line').style.display = 'none';
  }
}

let targetHeaders = { name: '客户名称', displayInfo: '合同总额', displayInfo2: '欠款金额' };

// 加载动态表头
async function loadTargetHeaders() {
  try {
    const res = await fetch('/api/target-headers?t=' + Date.now());
    targetHeaders = await res.json();
  } catch (e) {
    console.log('使用默认表头');
  }
}

// 加载目标列表
async function loadCompanies() {
  log(`📋 ${t('msg.loading_list', 'Loading target list...')}`);
  const response = await fetch('/api/targets');
  const rawCompanies = await response.json();

  targets = rawCompanies.map(item => {
    const name = typeof item === 'string' ? item : item.name;
    const displayInfo = typeof item === 'object' ? (item.displayInfo || item.orderDate || '') : '';
    const displayInfo2 = typeof item === 'object' ? (item.displayInfo2 || '') : '';
    const short = extractShortName(name);
    const core = normalizeCoreName(short);
    const coreNoRegion = stripLeadingRegion(core);

    return {
      full: name,
      displayInfo: displayInfo,
      displayInfo2: displayInfo2,
      normalized: normalizeText(name),
      short: short,
      core: core,
      coreNoRegion: coreNoRegion,
      keywords: extractKeywords(name),
      variants: generateVariants(name)
    };
  });

  buildTargetCharWeights();
  log(`✅ ${t('msg.loaded_count', 'Loaded')} ${targets.length} ${t('msg.targets', 'targets')}`);
}

function normalizeText(text) {
  if (!text) return '';
  return text
    // 移除空白字符、换行、常见标点以及 OCR 容易产生的噪点符号（如 ·, -, _, /, \, *, +, =)
    .replace(/[\s\n\r,.，。、：:；;！!？?（）()【】\[\]""''·\-—_\/\\*+=@#$%^&<>]/g, '')
    // 处理全角/半角数字
    .replace(/[0０]/g, '一').replace(/[1１]/g, '一').replace(/[2２]/g, '二')
    .replace(/[3３]/g, '三').replace(/[4４]/g, '四').replace(/[5５]/g, '五')
    .replace(/[6６]/g, '六').replace(/[7７]/g, '七').replace(/[8８]/g, '八')
    .replace(/[9９]/g, '九')
    // 统一处理常见的视觉混淆汉字（在此步骤合并，减少后续匹配负担）
    .replace(/曰/g, '日').replace(/囗/g, '口').replace(/入/g, '人');
}

function extractShortName(name) {
  return name
    .replace(/(集团有限责任公司|集团股份公司|有限责任公司|股份有限公司|股份公司|有限公司|分公司|总公司|集团|有限|控股)$/g, '')
    .replace(/[\s]/g, '');
}

function extractKeywords(name) {
  const normalized = extractShortName(name);
  const keywords = [];

  for (let len = 2; len <= Math.min(8, normalized.length); len++) {
    keywords.push(normalized.substring(0, len));
  }

  if (normalized.length > 4) {
    keywords.push(normalized.substring(2, Math.min(6, normalized.length)));
  }

  return keywords;
}

function generateVariants(name) {
  const variants = [name];
  const normalized = extractShortName(name);

  const confusions = [
    ['日', '曰'], ['口', '囗'], ['人', '入'], ['大', '太'],
    ['土', '士'], ['己', '已'], ['未', '末'], ['天', '夭'],
    ['干', '千'], ['厂', '广'], ['乌', '鸟'], ['拨', '拔'],
    ['设', '没'], ['德', '德'], ['防', '妨'], ['拨', '拔'],
    ['拔', '拨'], ['亨', '享'], ['崇', '祟'], ['戌', '戍'],
    ['份', '伤'], ['限', '根'], ['公', '松'], ['责', '青'],
  ];

  confusions.forEach(([a, b]) => {
    if (normalized.includes(a)) variants.push(normalized.replace(new RegExp(a, 'g'), b));
    if (normalized.includes(b)) variants.push(normalized.replace(new RegExp(b, 'g'), a));
  });

  return variants;
}

function normalizeCoreName(name) {
  return extractShortName(name || '');
}

function stripLeadingRegion(text) {
  const regionPrefixes = [
    '北京市', '重庆市', '天津市', '上海市', '杭州市', '宁波市', '温州市', '宁波', '温州',
    '江苏省', '浙江省', '广东省', '四川省', '湖北省', '山东省', '河南省', '河北省', '山西省', '辽宁省',
    '安徽省', '福建省', '贵州省', '甘肃省', '广西', '黑龙江', '吉林省', '江苏', '浙江', '广东', '四川',
    '湖北', '山东', '河南', '河北', '山西', '辽宁', '安徽', '福建', '贵州', '甘肃', '河南', '云南', '北京',
    '天津', '上海', '重庆', '吉林', '黑龙江', '海南', '香港', '澳门', '台湾'
  ];
  for (const prefix of regionPrefixes) {
    if (text.startsWith(prefix)) return text.slice(prefix.length);
  }
  return text;
}

function detectLeadingRegion(text) {
  const regionPrefixes = [
    '北京市', '重庆市', '天津市', '上海市', '杭州市', '宁波市', '温州市', '江苏省', '浙江省', '广东省',
    '四川省', '湖北省', '山东省', '河南省', '河北省', '山西省', '辽宁省', '安徽省', '福建省', '贵州省',
    '甘肃省', '吉林省', '黑龙江', '浙江', '江苏', '广东', '四川', '湖北', '山东', '河南', '河北',
    '山西', '辽宁', '安徽', '福建', '贵州', '甘肃', '福建', '黑龙江', '吉林', '北京', '天津', '上海', '重庆'
  ];
  for (const prefix of regionPrefixes) {
    if (text.startsWith(prefix)) return prefix;
  }
  return '';
}

function extractCompanyCandidates(text) {
  if (!text) return [];
  const suffixes = ['有限公司', '有限责任公司', '股份有限公司', '股份公司', '总公司', '分公司', '控股公司', '集团', '公司', '中心', '企业'];
  const suffixPattern = suffixes.join('|');
  const companyReg = new RegExp('([\\u4e00-\\u9fff]{2,60}(?:' + suffixPattern + '))', 'g');
  const rawParts = String(text).split(/[\\n\\r\\s,，;；:：|\\/]/);
  const candidates = new Set();
  const noisePrefixes = ['买方单位', '卖方单位', '签订方式', '乙方', '甲方', '单位', '买方', '卖方'];

  for (const rawPart of rawParts) {
    let part = normalizeText(rawPart);
    if (!part) continue;

    const matched = part.match(companyReg);
    if (matched && matched.length) {
      matched.forEach(item => {
        if (item.length >= 5) candidates.add(item);
      });
    }

    let filtered = part;
    noisePrefixes.forEach(prefix => {
      const pattern = new RegExp('^' + prefix);
      if (pattern.test(filtered)) filtered = filtered.replace(pattern, '');
    });
    if (filtered.length >= 5) candidates.add(filtered);
  }

  if (candidates.size === 0) candidates.add(normalizeText(text));
  return [...candidates];
}

function buildTargetCharWeights() {
  if (!targets.length) {
    targetCharWeights = {};
    return;
  }
  const docCount = targets.length;
  const docFreq = Object.create(null);

  targets.forEach(target => {
    const chars = new Set(target.core.split(''));
    chars.forEach(ch => {
      docFreq[ch] = (docFreq[ch] || 0) + 1;
    });
  });

  const weights = Object.create(null);
  Object.keys(docFreq).forEach(ch => {
    weights[ch] = 1 + Math.log((docCount + 1) / (docFreq[ch] + 1));
  });
  targetCharWeights = weights;
}

function getCharWeight(ch) {
  return targetCharWeights && targetCharWeights[ch] ? targetCharWeights[ch] : 1;
}

function calcWeightedOverlap(a, b) {
  const targetSet = new Set(String(b || '').split(''));
  if (targetSet.size === 0) return 0;
  const ocrSet = new Set(String(a || '').split(''));
  let matchedWeight = 0;
  let totalWeight = 0;

  targetSet.forEach(ch => {
    const w = getCharWeight(ch);
    totalWeight += w;
    if (ocrSet.has(ch)) matchedWeight += w;
  });

  return totalWeight > 0 ? matchedWeight / totalWeight : 0;
}

function calcBigramDice(a, b) {
  const s1 = String(a || '');
  const s2 = String(b || '');
  if (s1.length < 2 || s2.length < 2) return 0;

  const buildBigrams = (text) => {
    const set = new Set();
    for (let i = 0; i < text.length - 1; i++) set.add(text.substring(i, i + 2));
    return set;
  };

  const set1 = buildBigrams(s1);
  const set2 = buildBigrams(s2);
  if (set1.size === 0 && set2.size === 0) return 0;

  let overlap = 0;
  set1.forEach(v => { if (set2.has(v)) overlap++; });
  const union = set1.size + set2.size;
  return union > 0 ? (2 * overlap) / union : 0;
}

function calcLcsSimilarity(a, b) {
  const s1 = String(a || '');
  const s2 = String(b || '');
  const m = s1.length;
  const n = s2.length;
  if (m === 0 || n === 0) return 0;

  const prev = Array(n + 1).fill(0);
  for (let i = 1; i <= m; i++) {
    const cur = Array(n + 1).fill(0);
    for (let j = 1; j <= n; j++) {
      if (s1[i - 1] === s2[j - 1]) {
        cur[j] = prev[j - 1] + 1;
      } else {
        cur[j] = Math.max(prev[j], cur[j - 1]);
      }
    }
    prev.splice(0, prev.length, ...cur);
  }
  const lcsLen = prev[n];
  return lcsLen / Math.min(m, n);
}

function calcEditSimilarity(a, b) {
  const s1 = String(a || '');
  const s2 = String(b || '');
  if (s1.length === 0 || s2.length === 0) return 0;
  const dist = levenshteinDistance(s1, s2);
  const maxLen = Math.max(s1.length, s2.length);
  return Math.max(0, 1 - dist / maxLen);
}

function calcRegionalPenalty(a, b) {
  const aRegion = detectLeadingRegion(a);
  const bRegion = detectLeadingRegion(b);
  if (aRegion && bRegion) {
    return aRegion === bRegion ? 2 : -6;
  }
  if (aRegion || bRegion) return -2;
  return 0;
}

function calcScientificScore(ocrText, target) {
  let bestScore = 0;
  let bestType = '';
  const candidates = extractCompanyCandidates(ocrText);
  const t1 = target.core || target.short || target.normalized;
  const t2 = target.coreNoRegion || stripLeadingRegion(t1);

  const candidatePairs = [];
  candidates.forEach(candidate => {
    const c1 = normalizeCoreName(candidate);
    const c2 = stripLeadingRegion(c1);
    if (c1.length >= 2) candidatePairs.push({ label: '含前缀', candidate: c1, target: t1 });
    if (c2.length >= 2 && c2 !== c1) candidatePairs.push({ label: '去地域', candidate: c2, target: t1 });
    if (t2 && t2.length >= 2 && t2 !== t1) candidatePairs.push({ label: '目标去地域', candidate: c1, target: t2 });
  });

  if (candidatePairs.length === 0) return { score: 0, type: '' };

  candidatePairs.forEach(pair => {
    const overlap = calcWeightedOverlap(pair.candidate, pair.target);
    const dice = calcBigramDice(pair.candidate, pair.target);
    const edit = calcEditSimilarity(pair.candidate, pair.target);
    const lcs = calcLcsSimilarity(pair.candidate, pair.target);
    const regionDelta = calcRegionalPenalty(pair.candidate, pair.target);
    let score = 40 * overlap + 25 * dice + 20 * edit + 15 * lcs + regionDelta;
    score = Math.max(0, Math.min(100, score));

    if (score > bestScore) {
      bestScore = score;
      bestType = pair.label === '含前缀' ? '科学匹配' : `科学匹配·${pair.label}`;
    }
  });

  return { score: Math.round(bestScore), type: bestType || '科学匹配' };
}

// 初始化摄像头
async function initCamera() {
  log('📷 初始化摄像头...');
  statusText.textContent = '请求摄像头权限...';

  const constraints = {
    video: {
      facingMode: { ideal: 'environment' },
      width: { ideal: config.scan.width },
      height: { ideal: config.scan.height },
      frameRate: { ideal: config.scan.frameRate }
    }
  };

  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  video.srcObject = stream;

  // 显式调用 play()，某些移动浏览器 autoplay 对 srcObject 不生效
  try {
    await video.play();
  } catch (e) {
    log('⚠️ video.play() 失败: ' + e.message);
    throw e;
  }

  // === 关键修复：轮询等待有效视频尺寸 ===
  // 移动端 onloadedmetadata 可能触发时 videoWidth/videoHeight 仍为 0
  // WebKit Bug #217578: 不可见视频元素 produce 黑帧
  // WebKit Bug #252465: iOS PWA 可能冻结视频流
  const dims = await waitForVideoDimensions(video, 10000);
  canvas.width = dims.width;
  canvas.height = dims.height;

  log(`✅ 摄像头就绪 (${canvas.width}x${canvas.height})`);
}

/**
 * 轮询等待视频元素获得有效尺寸
 * 使用多个事件作为触发器，外加 rAF 轮询兜底
 */
function waitForVideoDimensions(videoEl, timeoutMs) {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();
    let resolved = false;
    let rafId = null;

    const check = () => {
      if (resolved) return;

      const w = videoEl.videoWidth;
      const h = videoEl.videoHeight;
      const ready = videoEl.readyState;

      // 有效尺寸且至少有当前帧数据
      if (w > 0 && h > 0 && ready >= 2) {
        resolved = true;
        cleanup();
        resolve({ width: w, height: h });
        return;
      }

      // iOS PWA 视频流冻结检测：track.muted 时尝试恢复
      const tracks = videoEl.srcObject ? videoEl.srcObject.getVideoTracks() : [];
      if (tracks.length > 0 && tracks[0].muted) {
        log('⚠️ 视频流被静音，尝试恢复...');
        tracks[0].enabled = false;
        tracks[0].enabled = true;
      }

      if (Date.now() - startTime > timeoutMs) {
        resolved = true;
        cleanup();
        reject(new Error(`摄像头就绪超时: videoWidth=${w}, videoHeight=${h}, readyState=${ready}`));
        return;
      }

      rafId = requestAnimationFrame(check);
    };

    const cleanup = () => {
      if (rafId) cancelAnimationFrame(rafId);
      videoEl.removeEventListener('loadedmetadata', onEvent);
      videoEl.removeEventListener('loadeddata', onEvent);
      videoEl.removeEventListener('playing', onEvent);
      videoEl.removeEventListener('timeupdate', onEvent);
    };

    const onEvent = () => { check(); };

    // 监听多个事件作为触发器，任一事件都可能携带有效尺寸
    videoEl.addEventListener('loadedmetadata', onEvent);
    videoEl.addEventListener('loadeddata', onEvent);
    videoEl.addEventListener('playing', onEvent);
    videoEl.addEventListener('timeupdate', onEvent);

    // 立即开始第一次检查
    check();
  });
}

// 初始化 WebSocket 连接
function initWebSocket() {
  return new Promise((resolve, reject) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const deviceInfo = getScannerDeviceInfo();
    const qs = new URLSearchParams({
      device_id: deviceInfo.deviceId,
      device_label: deviceInfo.label
    });
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/ocr?${qs.toString()}`);

    const connectTimeout = setTimeout(() => {
      ws.close();
      reject(new Error('WebSocket connection timeout'));
    }, 10000);

    ws.onopen = () => {
      clearTimeout(connectTimeout);
      log('🔗 WebSocket 引擎已连接');
      isWsConnected = true;
      wsReconnectAttempts = 0;
      // 重连成功后刷新目标列表
      loadCompanies().catch(() => {});
      updateStatus(STATE.SCANNING, '⏳', t('app.scanning', '自动扫描中...'));
      // 如果之前因断线而暂停扫描，重连后自动恢复
      if (shouldAutoScan && !scanInterval) {
        startScanning();
        log('▶️ 扫描已自动恢复');
      }
      resolve();
    };

    ws.onmessage = (event) => {
      isProcessing = false;
      if (processingTimeout) { clearTimeout(processingTimeout); processingTimeout = null; }
      try {
        const result = JSON.parse(event.data);
        const text = result.text || '';

        if (result.status === 'error') {
          updateStatus(STATE.NOT_MATCHED, '❌', '识别错误', text.substring(0, 100));
          log('❌ WS Error: ' + text);
          return;
        }

        if (text.trim().length === 0 && result.status === 'processing') {
          updateStatus(STATE.SCANNING, '⏳', t('app.scanning', 'Scanning...'));
          return;
        }

        if (result.status === 'success' && result.scan_count !== null && result.scan_count !== undefined) {
          incrementDailyCount(result.scan_count);
        }

        const matchRes = matchTarget(text);
        updateCandidates(matchRes.candidates || []);

        if (matchRes.matched) {
          if (matchRes.target === lastMatchedTarget) {
            consecutiveMatches++;
          } else {
            consecutiveMatches = 1;
            lastMatchedTarget = matchRes.target;
          }

          if (consecutiveMatches >= 1) {
            let wsInfoParts = [];
            if (matchRes.displayInfo) wsInfoParts.push(`${targetHeaders.displayInfo}: ${matchRes.displayInfo}`);
            if (matchRes.displayInfo2) wsInfoParts.push(`${targetHeaders.displayInfo2}: ${matchRes.displayInfo2}`);
            const infoLine = wsInfoParts.length ? `\n${wsInfoParts.join(' | ')}` : '';

            const rawText = text.trim().replace(/\s+/g, ' ');
            const rawPreview = rawText.length > 28 ? rawText.substring(0, 28) + '...' : rawText;
            const displayText = `识别：${rawPreview}\n匹配：${matchRes.target}\n${matchRes.score}% · ${matchRes.matchType}${infoLine}\n\n[ 点击屏幕继续 ]`;
            updateStatus(STATE.MATCHED, '✅', t('app.match_found'), displayText);
            log(`🎯 WS响应: ${matchRes.target} (${matchRes.score}%)`);

            if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
            
            // 匹配成功后进入等待点击状态
            isScanning = false;
            shouldAutoScan = false;
            if (scanInterval) { clearInterval(scanInterval); scanInterval = null; }
          }
        } else {
          consecutiveMatches = 0;
          lastMatchedTarget = null;

          if (text && text.trim().length >= 2) {
            const preview = text.trim().length > 40 ? text.trim().substring(0, 40) + '...' : text.trim();
            // 将 "扫描中..." 改为 "不匹配"，图标从 🔍 改为 ❌
            updateStatus(STATE.NOT_MATCHED, '❌', '不匹配', `${preview}\n\n[ 点击屏幕继续 ]`);
            
            // 不匹配也进入等待点击状态
            isScanning = false;
            shouldAutoScan = false;
            if (scanInterval) { clearInterval(scanInterval); scanInterval = null; }
            
            if (frameCount % 3 === 0 && config.ui.showDebug) {
              log(`❌ WS: ${text.substring(0, 30)}...`);
            }
          } else {
            // 将初始或空白状态的 "自动扫描中..." 也改为更明确的提示（此处保留 ⏳ 图标但改文字）
            updateStatus(STATE.SCANNING, '⏳', '正在扫描...');
          }
        }
      } catch (err) {
        log('WS Parse Err: ' + err.message);
      }
    };

    ws.onclose = () => {
      clearTimeout(connectTimeout);
      isWsConnected = false;
      // WebSocket 断开时暂停扫描，避免无效轮询
      stopScanning({ preserveIntent: true });
      log('⏸️ WebSocket 断开，扫描已自动暂停');
      // WebSocket 断开时清理前端识别状态，防止标志永久卡住
      if (isProcessing) {
        isProcessing = false;
        if (processingTimeout) { clearTimeout(processingTimeout); processingTimeout = null; }
        log('⚠️ 连接断开，已自动解锁识别状态');
      }
      wsReconnectAttempts++;
      if (wsReconnectAttempts <= WS_MAX_RECONNECT) {
        const delay = Math.min(WS_BASE_DELAY * Math.pow(2, wsReconnectAttempts - 1), 30000);
        log(`❌ WebSocket 已断开，${Math.round(delay/1000)}秒后第${wsReconnectAttempts}次重连...`);
        setTimeout(() => {
          initWebSocket().catch(() => {});
        }, delay);
      } else {
        log('❌ ' + t('app.ws_disconnected'));
        updateStatus(STATE.NOT_MATCHED, '❌', t('app.ws_disconnected'), t('app.ws_refresh'));
      }
    };

    ws.onerror = () => {
      clearTimeout(connectTimeout);
      reject(new Error('WebSocket error'));
    };
  });
}

// 开始扫描
function startScanning() {
  if (scanInterval) return;

  isScanning = true;
  shouldAutoScan = true;
  toggleBtn.innerHTML = ICONS['⏸'] || '⏸';
  toggleBtn.setAttribute('aria-label', t('app.pause', 'Pause'));

  // 恢复扫描线动画
  const scanLine = document.querySelector('.scan-line');
  if (scanLine) scanLine.style.animationPlayState = 'running';

  // 启动自动扫描循环：每 1.2 秒发送一帧
  scanInterval = setInterval(() => {
    if (isScanning && !isProcessing) {
      scanFrame();
    }
  }, 1200);

  log('▶️ 自动扫描已启动');
}

function stopScanning(options = {}) {
  if (scanInterval) {
    clearInterval(scanInterval);
    scanInterval = null;
  }
  isScanning = false;
  if (!options.preserveIntent) shouldAutoScan = false;
  toggleBtn.innerHTML = ICONS['▶'] || '▶';
  toggleBtn.setAttribute('aria-label', t('app.resume', 'Resume'));

  // 暂停扫描线动画
  const scanLine = document.querySelector('.scan-line');
  if (scanLine) scanLine.style.animationPlayState = 'paused';

  log('⏸️ ' + t('msg.paused', 'Paused'));
}

// 简化的图像裁剪 (AI不需要二值化预处理)
function cropROI(sourceCanvas) {
  const sw = sourceCanvas.width;
  const sh = sourceCanvas.height;

  const cropX = Math.floor(sw * (config.roi.x / 100));
  const cropY = Math.floor(sh * (config.roi.y / 100));
  const cropW = Math.floor(sw * (config.roi.width / 100));
  const cropH = Math.floor(sh * (config.roi.height / 100));

  const cropCanvas = document.createElement('canvas');
  cropCanvas.width = cropW;
  cropCanvas.height = cropH;
  const cropCtx = cropCanvas.getContext('2d');
  
  // 针对复印件优化：增加对比度和亮度，转为灰度
  // 这有助于 OCR 引擎更好地从灰色背景中分辨出文字
  cropCtx.filter = 'contrast(1.4) brightness(1.1) grayscale(1)';
  cropCtx.drawImage(sourceCanvas, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);

  return cropCanvas;
}

// 扫描单帧: 直接通过 WebSocket 发送
async function scanFrame() {
  if (isProcessing) {
    return;
  }
  if (!isWsConnected || ws.readyState !== WebSocket.OPEN) {
    isProcessing = false;
    log('⚠️ WS未连接, readyState=' + (ws ? ws.readyState : 'null'));
    return;
  }

  // === 防御性检查 ===
  if (video.readyState < 2) {
    log('⚠️ 视频未就绪 (readyState=' + video.readyState + ', paused=' + video.paused + ')');
    return;
  }
  if (video.paused) {
    log('⚠️ 视频已暂停，尝试恢复播放');
    video.play().catch(() => {});
    return;
  }
  if (canvas.width === 0 || canvas.height === 0) {
    log('⚠️ Canvas尺寸为0 (videoW=' + video.videoWidth + ', videoH=' + video.videoHeight + ')');
    return;
  }

  isProcessing = true;
  frameCount++;

  try {
    // 1. 截取当前帧
    ctx.drawImage(video, 0, 0);

    // 2. ROI裁剪 (不需要复杂预处理)
    const croppedCanvas = cropROI(canvas);

    // 额外防御：ROI裁剪后尺寸异常时跳过
    if (croppedCanvas.width === 0 || croppedCanvas.height === 0) {
      log('⚠️ ROI裁剪后尺寸为0，跳过帧');
      isProcessing = false;
      return;
    }

    const imageDataUrl = croppedCanvas.toDataURL('image/jpeg', 0.85);

    // 日志记录帧大小，方便调试时确认是否还有空白帧
    const frameSizeKB = Math.round(imageDataUrl.length / 1024);
    if (frameSizeKB < 2) {
      log('⚠️ 帧大小异常: ' + frameSizeKB + 'KB，可能为空白帧，跳过发送');
      isProcessing = false;
      return;
    }
    if (frameCount % 5 === 0) log('📤 帧 #' + frameCount + ' (' + frameSizeKB + 'KB)');

    // 3. 通过 WebSocket 发送二进制或 Base64 画面
    ws.send(imageDataUrl);
    // 清除旧的超时计时器，防止多个 timer 竞争
    if (processingTimeout) { clearTimeout(processingTimeout); processingTimeout = null; }
    // 超时保护：略长于服务端 OCR 超时，避免 GLM-OCR 慢响应时重复发帧压垮模型
    processingTimeout = setTimeout(() => {
      if (isProcessing) {
        isProcessing = false;
        log('⚠️ OCR 响应超时，已自动重置');
        updateStatus(STATE.SCANNING, '⏳', '正在扫描...');
      }
    }, OCR_RESPONSE_TIMEOUT_MS);
  } catch (err) {
    log('⚠️ 帧捕获/发送失败: ' + err.message);
    isProcessing = false;
    if (processingTimeout) { clearTimeout(processingTimeout); processingTimeout = null; }
  }
}


// 严格匹配算法 + 候选推荐
function matchTarget(ocrText) {
  if (!ocrText || ocrText.trim().length < 2) {
    return { matched: false, candidates: [] };
  }

  const normalized = normalizeText(ocrText);
  const minMatchRatio = config.matching.minMatchRatio || 0.6;
  const requirePrefix = config.matching.requirePrefix !== false;
  const minKeywordLength = config.matching.minKeywordLength || 5;

  let bestMatch = null;
  const candidates = [];

  for (const target of targets) {
    const targetNorm = target.normalized;
    const targetShort = target.short;
    const targetVariants = target.variants;
    let score = 0;
    let matchType = '';

    // 方法1: 完整名称匹配 (100%覆盖)
    if (normalized.includes(targetNorm)) {
      score = 100;
      matchType = '完整匹配';
      bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
      candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
      continue;
    }

    // 方法2: OCR文本完全被目标名称包含 (反向检查)
    if (targetNorm.includes(normalized)) {
      const ratio = normalized.length / targetNorm.length;
      if (ratio >= minMatchRatio) {
        score = Math.round(ratio * 100);
        matchType = '部分匹配';
        if (!bestMatch || score > bestMatch.score) {
          bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
        }
        candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
        continue;
      } else {
        // 低于阈值，作为候选但不匹配
        score = Math.round(ratio * 100);
        matchType = '低相似度';
        candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
      }
    }

    // 方法3: 短名称匹配（含视觉混淆变体）
    if (score === 0 && targetShort.length >= 3) {
      const allShorts = [targetShort, ...targetVariants.slice(1)];
      for (const variant of allShorts) {
        if (normalized.includes(variant)) {
          if (requirePrefix) {
            const prefix = variant.substring(0, Math.ceil(variant.length * 0.5));
            if (normalized.includes(prefix)) {
              score = 90;
              matchType = '短名称匹配';
              if (!bestMatch || score > bestMatch.score) {
                bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
              }
              candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
              break;
            }
          } else {
            score = 90;
            matchType = '短名称匹配';
            if (!bestMatch || score > bestMatch.score) {
              bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
            }
            candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
            break;
          }
        }
      }
      if (score > 0) continue;
    }

    // 方法4: 关键词匹配
    for (const keyword of target.keywords) {
      if (keyword.length >= minKeywordLength && normalized.includes(keyword)) {
        if (requirePrefix) {
          const prefixLen = Math.ceil(targetShort.length * 0.4);
          const prefix = targetShort.substring(0, prefixLen);
          if (keyword.includes(prefix) || normalized.includes(prefix)) {
            score = 80;
            matchType = '关键词匹配';
            if (!bestMatch || score > bestMatch.score) {
              bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
            }
            candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
            break;
          }
        } else {
          score = 80;
          matchType = '关键词匹配';
          if (!bestMatch || score > bestMatch.score) {
            bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
          }
          candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
          break;
        }
      }
    }

    // 方法5: 编辑距离匹配（比较完整短名，上限12字）
    if (normalized.length >= 6 && targetShort.length >= 6) {
      const cmpLen = Math.min(12, Math.max(normalized.length, targetShort.length));
      const distance = levenshteinDistance(normalized.substring(0, cmpLen), targetShort.substring(0, cmpLen));
      if (distance <= config.matching.levenshteinDistance) {
        score = 70 - (distance * 10);
        matchType = '模糊匹配';
        if (!bestMatch || score > bestMatch.score) {
          bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
        }
        candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
      } else if (distance <= 3) {
        // 作为低分候选
        score = 50 - (distance * 5);
        matchType = '可能相关';
        candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType });
      }
    }

    // 科学匹配：字符权重 + 顺序相关性
    if (normalized.length >= 2) {
      const scientific = calcScientificScore(ocrText, target);
      if (scientific.score > 0) {
        const shouldReplaceType = scientific.score > score;
        score = Math.max(score, scientific.score);
        if (shouldReplaceType) matchType = scientific.type;
        candidates.push({ target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score: score, matchType });
        if (score >= 65 && (!bestMatch || score > bestMatch.score)) {
          bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, displayInfo2: target.displayInfo2, score, matchType };
        }
      }
    }
  }

  // 排序并去重候选列表
  var uniqueCandidates = [];
  var seen = {};
  candidates
    .sort(function (a, b) { return b.score - a.score; })
    .forEach(function (c) {
      if (!seen[c.target]) {
        seen[c.target] = true;
        uniqueCandidates.push(c);
      }
    });

  // 返回最多5个候选
  var topCandidates = uniqueCandidates.slice(0, 5);

  if (bestMatch) {
    const bestScore = topCandidates[0] ? topCandidates[0].score : bestMatch.score;
    const isHighConfidence = bestScore >= 90;

    bestMatch.candidates = topCandidates;
    if (isHighConfidence) {
      return bestMatch;
    }
    return { matched: false, candidates: topCandidates };
  }

  return { matched: false, candidates: topCandidates };
}


function levenshteinDistance(s1, s2) {
  const m = s1.length, n = s2.length;
  const dp = Array(m + 1).fill(null).map(() => Array(n + 1).fill(0));

  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (s1[i - 1] === s2[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1];
      } else {
        dp[i][j] = 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
      }
    }
  }

  return dp[m][n];
}

function updateStatus(state, icon, text, targetInfo = '') {
  overlay.className = `overlay ${state}`;
  // ICONS maps to predefined SVG strings (safe, no user input)
  const iconHtml = ICONS[icon];
  if (iconHtml) { statusIcon.innerHTML = iconHtml; } else { statusIcon.textContent = icon; }
  statusText.textContent = text;
  matchedTargetEl.textContent = targetInfo;

  // 关键修正：只有在出现结果（匹配或不匹配）且扫描暂停时，才允许点击全屏
  // 否则会拦截“开始扫描”按钮的点击事件
  const isResultState = (state === STATE.MATCHED || state === STATE.NOT_MATCHED);
  overlay.style.pointerEvents = isResultState ? 'auto' : 'none';
  overlay.style.cursor = isResultState ? 'pointer' : 'default';

  if (matchDismissTimer) { clearTimeout(matchDismissTimer); matchDismissTimer = null; }
}

// 更新候选目标列表
function updateCandidates(candidates) {
  try {
    const candidatesList = document.getElementById('candidates-list');
    const candidatesPanel = document.getElementById('candidates-panel');

    // 元素不存在时直接返回
    if (!candidatesList || !candidatesPanel) {
      return;
    }

    if (!candidates || candidates.length === 0) {
      candidatesPanel.classList.add('hidden');
      return;
    }

    candidatesPanel.classList.remove('hidden');

    candidatesList.innerHTML = candidates.map(function (c) {
      var scoreClass = c.score >= 80 ? 'high-score' : c.score >= 60 ? 'medium-score' : 'low-score';
      var scoreColor = c.score >= 80 ? '#14B8A6' : c.score >= 60 ? '#F97316' : '#64748B';

      // 安全处理可能缺失的字段
      var targetName = c.target || '未知目标';
      var infoParts = [];
      if (c.displayInfo) infoParts.push(targetHeaders.displayInfo + ': ' + c.displayInfo);
      if (c.displayInfo2) infoParts.push(targetHeaders.displayInfo2 + ': ' + c.displayInfo2);
      var infoText = infoParts.join(' | ');
      var score = c.score || 0;
      var matchType = c.matchType || '未知';

      return '<div class="candidate-item ' + scoreClass + '">' +
        '<div class="candidate-info">' +
        '<div class="candidate-name">' + targetName + '</div>' +
        (infoText ? '<div class="candidate-date">ℹ️ ' + infoText + '</div>' : '') +
        '</div>' +
        '<div class="candidate-score">' +
        '<div class="score-value" style="color: ' + scoreColor + '">' + score + '%</div>' +
        '<div class="score-type">' + matchType + '</div>' +
        '</div>' +
        '</div>';
    }).join('');
  } catch (e) {
    console.error('updateCandidates error:', e);
  }
}

// === 菜单控制 ===

let menuOpen = false;

function toggleMenu() {
  menuOpen = !menuOpen;
  const menu = document.getElementById('action-menu');
  const overlay = document.getElementById('menu-overlay');
  if (menuOpen) {
    menu.classList.add('open');
    overlay.classList.add('open');
  } else {
    closeMenu();
  }
}

function closeMenu() {
  menuOpen = false;
  const menu = document.getElementById('action-menu');
  const overlay = document.getElementById('menu-overlay');
  if (menu) menu.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
}

// 语言切换后更新菜单标签
window.onLangChanged = function() {
  const label = document.getElementById('lang-label');
  if (label) label.textContent = currentLang === 'en' ? '切换语言' : 'Switch Language';
};

function bindEvents() {
  toggleBtn.addEventListener('click', async () => {
    if (isScanning) {
      stopScanning();
    } else {
      // 每次恢复前重新加载目标列表，确保与后台同步
      try {
        await loadCompanies();
      } catch (e) {
        log('⚠️ 刷新名单失败，使用缓存数据');
      }
      startScanning();
    }
  });



  // 全局屏幕点击处理：用于恢复扫描或强制解锁
  overlay.addEventListener('click', (e) => {
    // 忽略对菜单和控制按钮的点击
    if (e.target.closest('.action-menu') || e.target.closest('.controls')) return;

    // 1. 如果当前显示了结果（已暂停），点击则恢复扫描
    if (!isScanning && isWsConnected) {
      log('🖱️ 用户点击屏幕，继续识别...');
      consecutiveMatches = 0;
      lastMatchedTarget = null;
      updateStatus(STATE.SCANNING, '⏳', '正在准备扫描...');
      startScanning();
      return;
    }
    
    // 2. 如果卡在“正在识别”状态（isProcessing=true），点击屏幕强制解锁并重试
    if (isProcessing) {
      log('🖱️ 用户点击屏幕，强制解锁识别状态...');
      isProcessing = false;
      if (processingTimeout) { clearTimeout(processingTimeout); processingTimeout = null; }
      updateStatus(STATE.SCANNING, '⏳', '状态已重置，正在重新扫描...');
    }
  });
}

// 手动重置扫描器（解决卡死问题）
async function resetScanner() {
  log('🔄 手动重置扫描器...');

  // 1. 清理状态
  isProcessing = false;
  if (processingTimeout) { clearTimeout(processingTimeout); processingTimeout = null; }
  consecutiveMatches = 0;
  lastMatchedTarget = null;

  // 2. 关闭旧 WebSocket
  if (ws) {
    try { ws.close(); } catch (e) {}
    ws = null;
  }
  isWsConnected = false;
  wsReconnectAttempts = 0;

  // 3. 重新加载配置和名单
  try { await loadConfig(); } catch (e) { log('⚠️ 配置加载失败'); }
  try { await loadCompanies(); } catch (e) { log('⚠️ 名单加载失败'); }

  // 4. 重建 WebSocket
  try {
    await initWebSocket();
    log('✅ 重置完成');
    updateStatus(STATE.SCANNING, '⏳', '已重置，请继续扫描');
  } catch (e) {
    log('❌ WebSocket 重建失败: ' + e.message);
    updateStatus(STATE.NOT_MATCHED, '❌', '重置失败', '请刷新页面');
  }
}

// 日志辅助函数（使用 textContent 防止 XSS）
function log(msg) {
  const time = new Date().toLocaleTimeString();
  console.log(`[${time}] ${msg}`);

  // 仅在调试面板可见时写入DOM
  const debugEl = document.getElementById('debug');
  if (debugEl && debugEl.classList.contains('visible')) {
    // 安全方式：用 DOM 操作代替 innerHTML
    const line = document.createElement('div');
    line.textContent = `[${time}] ${msg}`;
    debugEl.appendChild(line);
    // 保持最多 30 条日志
    while (debugEl.children.length > 30) {
      debugEl.removeChild(debugEl.firstChild);
    }
    debugEl.scrollTop = debugEl.scrollHeight;
  }
}

// Page Visibility API：页面切到后台时暂停扫描，回到前台时恢复
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (isScanning) {
      stopScanning({ preserveIntent: true });
      log('⏸️ 页面进入后台，扫描已暂停');
    }
  } else {
    refreshDailyTotalCount();
    if (shouldAutoScan && !scanInterval && isWsConnected) {
      startScanning();
      log('▶️ 页面回到前台，扫描已恢复');
    }
  }
});

document.addEventListener('DOMContentLoaded', init);

// ============ 连接模式管理 ============


async function loadNetworkInfo() {
  try {
    const res = await fetch('/api/network-info?t=' + Date.now());
    networkInfo = await res.json();
  } catch (e) {
    log('⚠️ 网络信息加载失败');
    networkInfo = null;
  }
}

function toggleDebug() {
  const debugEl = document.getElementById('debug');
  if (!debugEl) return;
  debugEl.classList.toggle('visible');
  const isVisible = debugEl.classList.contains('visible');
  log(isVisible ? '调试日志已显示' : '调试日志已隐藏');
}

function toggleConnPanel() {
  const panel = document.getElementById('conn-panel');
  if (!panel) return;
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden')) {
    updateConnPanelUI();
  }
}

function setConnMode(mode, url) {
  if (!networkInfo && !url) {
    const diagEl = document.getElementById('conn-diag');
    if (diagEl) diagEl.textContent = '网络信息未加载，请稍后重试';
    return;
  }
  if (mode === currentConnMode && !url) {
    toggleConnPanel();
    return;
  }
  const targetUrl = url || networkInfo.usb_url;
  if (targetUrl) {
    window.location.href = targetUrl;
  }
}

function updateConnPanelUI() {
  const usbMode = document.getElementById('conn-mode-usb');
  const adbMode = document.getElementById('conn-mode-adb');
  const usbDesc = document.getElementById('conn-desc-usb');
  const adbPanel = document.getElementById('adb-panel');
  const statusEl = document.getElementById('conn-status');

  if (usbMode) usbMode.classList.toggle('active', currentConnMode === 'usb');
  if (adbMode) adbMode.classList.toggle('active', currentConnMode === 'adb');

  // 显示/隐藏对应的详情面板
  if (adbPanel) adbPanel.style.display = (currentConnMode === 'adb') ? 'block' : 'none';

  if (!networkInfo) {
    if (statusEl) statusEl.textContent = '无法获取网络信息';
    return;
  }

  if (usbDesc) usbDesc.textContent = networkInfo.usb_url || '';

  if (statusEl) {
    const modeLabels = {
      usb: t('conn.status_usb') || 'Current: USB',
      adb: 'Current: 无线调试 (ADB)'
    };
    statusEl.textContent = modeLabels[currentConnMode] || modeLabels.usb;
  }
}

function updateAdbSteps() {
  for (let i = 0; i < 5; i++) {
    const el = document.getElementById('adb-step-' + (i + 1));
    if (!el) continue;
    el.classList.remove('active', 'done');
    if (adbStepStates[i] === 1) el.classList.add('active');
    if (adbStepStates[i] === 2) el.classList.add('done');

    const num = el.querySelector('.adb-step__num');
    if (num) {
      if (adbStepStates[i] === 2) {
        num.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
      } else {
        num.textContent = String(i + 1);
      }
    }
  }
}

function showAdbPanel() {
  currentConnMode = 'adb';
  adbStepStates = [1, 0, 0, 0, 0];
  updateAdbSteps();
  updateConnPanelUI();
  checkAdbStatus();
}

async function checkAdbStatus() {
  const statusEl = document.getElementById('adb-status');
  if (!statusEl) return;
  statusEl.textContent = '检测 ADB 状态中…';
  try {
    const res = await fetch('/api/adb-wifi-status?t=' + Date.now());
    const data = await res.json();
    if (data.connected) {
      if (data.mode === 'usb') {
        statusEl.textContent = 'USB 已连接 (' + (data.usb_device || 'device') + ')';
        adbStepStates = [2, 1, 0, 0, 0];
        updateAdbSteps();
      } else if (data.mode === 'wifi') {
        statusEl.textContent = '无线调试已连接 (' + (data.wifi_ip || '') + ')';
        adbStepStates = [2, 2, 2, 2, 1];
        updateAdbSteps();
      }
    } else {
      statusEl.textContent = data.message || '未检测到 ADB 设备，请用 USB 连接手机';
      adbStepStates = [1, 0, 0, 0, 0];
      updateAdbSteps();
    }
  } catch (e) {
    statusEl.textContent = 'ADB 检测失败: ' + e.message;
  }
}

async function startAdbWifi() {
  const btn = document.getElementById('adb-start-btn');
  const statusEl = document.getElementById('adb-status');
  const cmdBox = document.getElementById('adb-cmd-box');
  const cmdHint = document.getElementById('adb-cmd-hint');
  if (btn) { btn.disabled = true; btn.textContent = '开启中…'; }
  if (statusEl) statusEl.textContent = '正在开启 ADB 网络模式…';
  try {
    const res = await fetch('/api/adb-wifi-start', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'success') {
      adbWifiIp = data.wifi_ip || null;
      if (statusEl) statusEl.textContent = '已开启！请拔掉USB，然后在电脑终端执行步骤4的命令';
      if (btn) btn.textContent = '已开启';
      if (cmdHint) cmdHint.style.display = 'inline';
      // 更新命令框显示实际IP
      if (cmdBox && adbWifiIp) {
        cmdBox.innerHTML = 'adb connect ' + adbWifiIp + ':5555<br>adb reverse tcp:8093 tcp:8093';
      }
      // 步骤1-2完成，步骤3激活（等待拔线）
      adbStepStates = [2, 2, 1, 0, 0];
      updateAdbSteps();
    } else {
      if (statusEl) statusEl.textContent = '开启失败: ' + data.message;
      if (btn) { btn.disabled = false; btn.textContent = '开启无线调试'; }
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = '请求失败: ' + e.message;
    if (btn) { btn.disabled = false; btn.textContent = '开启无线调试'; }
  }
}

async function repairAdb() {
  const btn = document.getElementById('adb-repair-btn');
  const statusEl = document.getElementById('adb-status');
  if (btn) { btn.disabled = true; btn.textContent = '检测中…'; }
  if (statusEl) statusEl.textContent = '正在重启 ADB 并重新检测…';
  try {
    const res = await fetch('/api/adb-repair', { method: 'POST' });
    const data = await res.json();
    if (statusEl) statusEl.textContent = data.message || 'ADB 检测完成';
    if (data.status === 'success') {
      adbStepStates = [2, 1, 0, 0, 0];
    } else {
      adbStepStates = [1, 0, 0, 0, 0];
    }
    updateAdbSteps();
  } catch (e) {
    if (statusEl) statusEl.textContent = 'ADB 检测失败: ' + e.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '重启 ADB 检测'; }
  }
}

function copyAdbCmd() {
  const cmdBox = document.getElementById('adb-cmd-box');
  if (!cmdBox) return;
  const text = cmdBox.innerText;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.getElementById('adb-copy-cmd-btn');
      if (btn) { btn.textContent = '已复制'; setTimeout(() => btn.textContent = '复制命令', 2000); }
    });
  } else {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    const btn = document.getElementById('adb-copy-cmd-btn');
    if (btn) { btn.textContent = '已复制'; setTimeout(() => btn.textContent = '复制命令', 2000); }
  }
}

async function connectAdbWifi() {
  const statusEl = document.getElementById('adb-status');
  if (statusEl) statusEl.textContent = '正在通过 WiFi 连接 ADB…';
  try {
    const res = await fetch('/api/adb-wifi-connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wifi_ip: adbWifiIp })
    });
    const data = await res.json();
    if (data.status === 'success') {
      if (statusEl) statusEl.textContent = '连接成功！请刷新手机页面 (localhost:8093)';
    } else {
      if (statusEl) statusEl.textContent = '连接失败: ' + data.message;
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = '请求失败: ' + e.message;
  }
}

// === 每日计数器逻辑 ===
function getTodayDateStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function initDailyCounter() {
  syncLocalCounterDate();
  updateDailyCounterUI();
  refreshDailyTotalCount();
  if (!scanStatsPollTimer) {
    scanStatsPollTimer = setInterval(refreshDailyTotalCount, SCAN_STATS_POLL_MS);
  }
}

function syncLocalCounterDate(dateStr) {
  const today = dateStr || getTodayDateStr();
  const storedDate = localStorage.getItem('scanDate');
  if (storedDate !== today) {
    dailyScanCount = 0;
    localStorage.setItem('scanDate', today);
    localStorage.setItem('scanCount', '0');
    lastScanDate = today;
    return;
  }
  dailyScanCount = Math.max(0, parseInt(localStorage.getItem('scanCount') || '0', 10) || 0);
  lastScanDate = today;
}

function saveLocalScanCount() {
  const today = lastScanDate || getTodayDateStr();
  localStorage.setItem('scanDate', today);
  localStorage.setItem('scanCount', String(Math.max(0, dailyScanCount)));
  lastScanDate = today;
}

function setTotalScanCount(count) {
  const parsed = parseInt(count, 10);
  if (Number.isFinite(parsed)) {
    totalScanCount = Math.max(0, parsed);
  }
}

async function refreshDailyTotalCount() {
  try {
    const res = await fetch('/api/scan-stats?t=' + Date.now());
    if (!res.ok) return;
    const data = await res.json();
    if (data.date) syncLocalCounterDate(data.date);
    setTotalScanCount(data.count);
    updateDailyCounterUI();
  } catch (e) {
    log('⚠️ 扫描总数同步失败: ' + e.message);
  }
}

function incrementDailyCount(serverCount) {
  syncLocalCounterDate();
  dailyScanCount++;
  saveLocalScanCount();
  setTotalScanCount(serverCount);
  updateDailyCounterUI();
  if (serverCount === null || serverCount === undefined) refreshDailyTotalCount();
}

function resetDailyCount() {
  if (confirm(t('app.confirm_reset_count', '确定要重置今日的扫描计数吗？'))) {
    dailyScanCount = 0;
    saveLocalScanCount();
    updateDailyCounterUI();
  }
}

async function adjustDailyCount(delta) {
  delta = Number(delta);
  if (delta !== 1 && delta !== -1) return;

  syncLocalCounterDate();
  const prevLocal = dailyScanCount;
  const prevTotal = totalScanCount;

  dailyScanCount = Math.max(0, dailyScanCount + delta);
  totalScanCount = Math.max(0, totalScanCount + delta);
  saveLocalScanCount();
  updateDailyCounterUI(true);

  try {
    const deviceInfo = getScannerDeviceInfo();
    const res = await fetch('/api/scan-stats/adjust', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        delta,
        device_id: deviceInfo.deviceId,
        device_label: deviceInfo.label
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'adjust failed');
    if (data.date) syncLocalCounterDate(data.date);
    setTotalScanCount(data.count);
    updateDailyCounterUI();
  } catch (e) {
    dailyScanCount = prevLocal;
    totalScanCount = prevTotal;
    saveLocalScanCount();
    updateDailyCounterUI();
    log('⚠️ 手动调整扫描次数失败: ' + e.message);
  }
}

function updateDailyCounterUI() {
  if (scanCounterTotalValEl) scanCounterTotalValEl.textContent = totalScanCount;
  if (scanCounterLocalValEl) scanCounterLocalValEl.textContent = dailyScanCount;
  if (scanCountMinusBtn) scanCountMinusBtn.disabled = totalScanCount <= 0 && dailyScanCount <= 0;
  if (scanCountPlusBtn) scanCountPlusBtn.disabled = false;
}
