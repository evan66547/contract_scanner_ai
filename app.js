/**
 * 合同扫描器 - AI增强版
 * OCR引擎: GLM-OCR via Ollama (本地AI)
 */

// 全局状态
let targets = [];
let ocrReady = false; // AI引擎是否就绪
let isScanning = true;
let scanInterval = null;
let consecutiveMatches = 0;
let lastMatchedTarget = null;
let isProcessing = false;
let lastScanTime = 0;
let frameCount = 0;
let config = {};
let ws = null;
let isWsConnected = false;
let wsReconnectAttempts = 0;
const WS_MAX_RECONNECT = 10;
const WS_BASE_DELAY = 1000;

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



// 初始化
async function init() {
  log('🚀 开始初始化...');

  // 检查安全上下文
  if (!window.isSecureContext) {
    console.warn('当前不是安全上下文');
    log('❌ 警告: 当前不是安全上下文(HTTPS/localhost)');
    log('无法访问摄像头');
  } else {
    log('✅ 安全上下文: 是');
  }

  // 检查API支持
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    // log('❌ 错误: 浏览器不支持 mediaDevices API');
  }

  try {

    log('1. 正在加载配置...');
    await loadConfig();
    log('✅ 配置加载成功');

    log('2. ' + t('msg.loading_list', 'Loading target list...'));
    await loadCompanies();
    log('✅ ' + t('msg.loaded', 'Target list loaded successfully'));

    statusText.textContent = '准备就绪';
    const startBtn = document.getElementById('start-btn');
    startBtn.style.display = 'block';

    if (!window.isSecureContext) {
      statusText.textContent = '⚠️ 非安全连接';
      log('❌ 摄像头需要HTTPS或localhost');
      alert('错误：无法访问摄像头！\n\n解决方案：\n1. USB连接电脑\n2. 运行 adb reverse tcp:8080 tcp:8080\n3. 手机访问 http://localhost:8080');
      startBtn.textContent = "拍照上传 (兜底模式)";
      startBtn.style.background = "#ffaa00";
    }

    // 检查是否带有 autostart 参数（从管理面板远程启动）
    const urlParams = new URLSearchParams(window.location.search);
    const autoStart = urlParams.get('autostart') === '1';

    startBtn.onclick = async () => {
      if (!window.isSecureContext || !navigator.mediaDevices) {
        document.getElementById('file-input').click();
        return;
      }

      startBtn.style.display = 'none';
      log('🚀 用户点击启动...');

      try {
        log('3. 初始化摄像头...');
        await initCamera();
        log('✅ 摄像头就绪');

        // 初始化 WebSocket
        log('4. 初始化 WebSocket 引擎...');
        await initWebSocket();
        
        applyConfigToUI();
        startScanning();
        bindEvents();
      } catch (e) {
        log('❌ 启动失败: ' + e.message);
        alert('启动失败: ' + e.message);
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
      updateStatus('not-matched', '🚫', '需要摄像头权限', '请在浏览器设置中允许访问摄像头\n\n刷新页面重试');
    } else if (error.name === 'NotFoundError') {
      updateStatus('not-matched', '📷', '未找到摄像头', '请确保设备有可用的摄像头');
    } else {
      updateStatus('not-matched', '❌', '系统错误', error.message);
    }
  }
}

// 加载配置
async function loadConfig() {
  log('⚙️ 加载配置...');
  const res = await fetch('/api/config?t=' + Date.now());
  config = await res.json();
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

// 加载目标列表
async function loadCompanies() {
  log(`📋 ${t('msg.loading_list', 'Loading target list...')}`);
  const response = await fetch('/api/targets');
  const rawCompanies = await response.json();

  targets = rawCompanies.map(item => {
    const name = typeof item === 'string' ? item : item.name;
    const displayInfo = typeof item === 'object' ? (item.displayInfo || item.orderDate || '') : '';

    return {
      full: name,
      displayInfo: displayInfo,
      normalized: normalizeText(name),
      short: extractShortName(name),
      keywords: extractKeywords(name),
      variants: generateVariants(name)
    };
  });

  log(`✅ ${t('msg.loaded_count', 'Loaded')} ${targets.length} ${t('msg.targets', 'targets')}`);
}

function normalizeText(text) {
  return text
    .replace(/[\s\n\r,.，。、：:；;！!？?（）()【】\[\]""''·\-—_\/\\]/g, '')
    .replace(/[0０]/g, '〇')
    .replace(/[1１]/g, '一')
    .replace(/[2２]/g, '二');
}

function extractShortName(name) {
  return name
    .replace(/(有限责任目标|有限目标|股份有限目标|股份目标|集团有限目标|集团|有限|分目标|总目标|控股)$/g, '')
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
  ];

  confusions.forEach(([a, b]) => {
    if (normalized.includes(a)) variants.push(normalized.replace(new RegExp(a, 'g'), b));
    if (normalized.includes(b)) variants.push(normalized.replace(new RegExp(b, 'g'), a));
  });

  return variants;
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

  await new Promise(resolve => {
    video.onloadedmetadata = () => {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      resolve();
    };
  });

  log(`✅ 摄像头就绪 (${video.videoWidth}x${video.videoHeight})`);
}

// 初始化 WebSocket 连接
function initWebSocket() {
  return new Promise((resolve, reject) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/ocr`);
    
    ws.onopen = () => {
      log('🔗 WebSocket 引擎已连接');
      isWsConnected = true;
      ocrReady = true;
      wsReconnectAttempts = 0; // 连接成功重置重连计数器
      updateStatus('scanning', '⏳', t('app.scanning', 'Scanning...'));
      resolve();
    };
    
    ws.onmessage = (event) => {
      isProcessing = false; // 服务器返回结果，解锁下一帧
      try {
        const result = JSON.parse(event.data);
        const text = result.text || '';
        if (text.trim().length === 0 && result.status === "processing") return;
        
        // 匹配过程与原先一致
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
            const infoLine = matchRes.displayInfo ? `\\n\\n${t('app.info_prefix')}${matchRes.displayInfo}` : '';
            const displayText = `${matchRes.target}${infoLine}`;
            updateStatus('matched', '✅', t('app.match_found'), displayText);
            log(`🎯 WS响应: ${matchRes.target} (${matchRes.score}%)`);
            
            if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
          }
        } else {
          consecutiveMatches = 0;
          lastMatchedTarget = null;
          
          if (text && text.trim().length >= 2) {
            updateStatus('not-matched', '❌', t('app.not_target', 'Not Target Object'));
            if (frameCount % 3 === 0 && config.ui.showDebug) {
              log(`❌ WS: ${text.substring(0, 30)}...`);
            }
          } else {
            updateStatus('scanning', '⏳', t('app.scanning', 'Scanning...'));
          }
        }
      } catch (err) {
        log('WS Parse Err: ' + err.message);
      }
    };
    
    ws.onclose = () => {
      isWsConnected = false;
      ocrReady = false;
      wsReconnectAttempts++;
      if (wsReconnectAttempts <= WS_MAX_RECONNECT) {
        const delay = Math.min(WS_BASE_DELAY * Math.pow(2, wsReconnectAttempts - 1), 30000);
        log(`❌ WebSocket 已断开，${Math.round(delay/1000)}秒后第${wsReconnectAttempts}次重连...`);
        setTimeout(() => {
          initWebSocket().catch(err => {
            log('⚠️ 重连失败: ' + err.message);
          });
        }, delay);
      } else {
        log('❌ ' + t('app.ws_disconnected'));
        updateStatus('not-matched', '❌', t('app.ws_disconnected'), t('app.ws_refresh'));
      }
    };
    
    ws.onerror = (err) => {
      log('⚠️ WebSocket 发生错误');
    };
  });
}

// 开始扫描
function startScanning() {
  if (scanInterval) return;

  isScanning = true;
  toggleBtn.textContent = t('app.pause', 'Pause');

  const interval = config.scan.interval || 1500;
  scanInterval = setInterval(async () => {
    if (!isScanning || !ocrReady || isProcessing) return;

    try {
      isProcessing = true; // 发送数据前上锁
      await scanFrame();
    } catch (error) {
      log('Scan Err: ' + error.message);
      isProcessing = false;
    }
  }, interval);

  log(`▶️ WS Scan Started (${interval}ms)`);
}

function stopScanning() {
  if (scanInterval) {
    clearInterval(scanInterval);
    scanInterval = null;
  }
  isScanning = false;
  toggleBtn.textContent = t('app.resume', 'Resume');
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
  cropCtx.drawImage(sourceCanvas, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);

  return cropCanvas;
}

// 扫描单帧: 直接通过 WebSocket 发送
async function scanFrame() {
  if (!isWsConnected || ws.readyState !== WebSocket.OPEN) {
    isProcessing = false;
    return;
  }
  
  frameCount++;

  // 1. 截取当前帧
  ctx.drawImage(video, 0, 0);

  // 2. ROI裁剪 (不需要复杂预处理)
  const croppedCanvas = cropROI(canvas);
  const imageDataUrl = croppedCanvas.toDataURL('image/jpeg', 0.85);

  try {
    // 3. 通过 WebSocket 发送二进制或 Base64 画面
    ws.send(imageDataUrl);
    // 注意: isProcessing 会在 ws.onmessage 收到服务端返回时才被释放为 false，实现完美的并行控制。
  } catch (err) {
    log('⚠️ WS 推送失败: ' + err.message);
    isProcessing = false;
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
    let score = 0;
    let matchType = '';

    // 方法1: 完整名称匹配 (100%覆盖)
    if (normalized.includes(targetNorm)) {
      score = 100;
      matchType = '完整匹配';
      bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, score, matchType };
      candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
      continue;
    }

    // 方法2: OCR文本完全被目标名称包含 (反向检查)
    if (targetNorm.includes(normalized)) {
      const ratio = normalized.length / targetNorm.length;
      if (ratio >= minMatchRatio) {
        score = Math.round(ratio * 100);
        matchType = '部分匹配';
        if (!bestMatch || score > bestMatch.score) {
          bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, score, matchType };
        }
        candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
        continue;
      } else {
        // 低于阈值，作为候选但不匹配
        score = Math.round(ratio * 100);
        matchType = '低相似度';
        candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
      }
    }

    // 方法3: 严格的短名称匹配
    if (targetShort.length >= 3 && normalized.includes(targetShort)) {
      if (requirePrefix) {
        const prefix = targetShort.substring(0, Math.ceil(targetShort.length * 0.5));
        if (normalized.includes(prefix)) {
          score = 90;
          matchType = '短名称匹配';
          if (!bestMatch || score > bestMatch.score) {
            bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, score, matchType };
          }
          candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
          continue;
        }
      } else {
        score = 90;
        matchType = '短名称匹配';
        if (!bestMatch || score > bestMatch.score) {
          bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, score, matchType };
        }
        candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
        continue;
      }
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
              bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, score, matchType };
            }
            candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
            break;
          }
        } else {
          score = 80;
          matchType = '关键词匹配';
          if (!bestMatch || score > bestMatch.score) {
            bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, score, matchType };
          }
          candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
          break;
        }
      }
    }

    // 方法5: 编辑距离匹配
    if (normalized.length >= 6 && targetShort.length >= 6) {
      const distance = levenshteinDistance(normalized.substring(0, 8), targetShort.substring(0, 8));
      if (distance <= config.matching.levenshteinDistance) {
        score = 70 - (distance * 10);
        matchType = '模糊匹配';
        if (!bestMatch || score > bestMatch.score) {
          bestMatch = { matched: true, target: target.full, displayInfo: target.displayInfo, score, matchType };
        }
        candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
      } else if (distance <= 3) {
        // 作为低分候选
        score = 50 - (distance * 5);
        matchType = '可能相关';
        candidates.push({ target: target.full, displayInfo: target.displayInfo, score, matchType });
      }
    }

    // 新增：主动计算字符重叠相似度（确保每个目标都有机会成为候选）
    if (score === 0 && normalized.length >= 2) {
      // 计算字符重叠率
      var overlap = 0;
      var shortText = targetShort.length < normalized.length ? targetShort : normalized;
      var longText = targetShort.length < normalized.length ? normalized : targetShort;

      for (var i = 0; i < shortText.length; i++) {
        if (longText.indexOf(shortText[i]) !== -1) {
          overlap++;
        }
      }

      var overlapRatio = overlap / shortText.length;
      if (overlapRatio >= 0.4) {
        score = Math.round(overlapRatio * 40); // 最高40分
        matchType = '字符相似';
        candidates.push({ target: target.full, displayInfo: target.displayInfo, score: score, matchType: matchType });
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
    bestMatch.candidates = topCandidates;
    return bestMatch;
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
  statusIcon.textContent = icon;
  statusText.textContent = text;
  matchedTargetEl.textContent = targetInfo;

  overlay.style.pointerEvents = (state === 'matched' || state === 'not-matched') ? 'auto' : 'none';
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
      var scoreColor = c.score >= 80 ? '#00ff88' : c.score >= 60 ? '#ffaa00' : '#888';

      // 安全处理可能缺失的字段
      var targetName = c.target || '未知目标';
      var infoText = c.displayInfo || '';
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

function bindEvents() {
  toggleBtn.addEventListener('click', () => {
    if (isScanning) {
      stopScanning();
    } else {
      updateStatus('scanning', '⏳', '正在识别...');
      startScanning();
    }
  });



  overlay.addEventListener('click', (e) => {
    if (e.target === overlay && (overlay.classList.contains('matched') || overlay.classList.contains('not-matched'))) {
      updateStatus('scanning', '⏳', '正在识别...');
      consecutiveMatches = 0;
      lastMatchedTarget = null;
    }
  });
}

// 兜底方案：处理文件上传/拍照
async function handleFileUpload(input) {
  if (input.files && input.files[0]) {
    const file = input.files[0];
    const img = new Image();

    statusText.textContent = '正在处理图片...';

    img.onload = async () => {
      canvas.width = img.width;
      canvas.height = img.height;
      ctx.drawImage(img, 0, 0);

      video.style.display = 'none';
      canvas.style.display = 'block';
      canvas.style.width = '100%';
      canvas.style.height = '100%';
      canvas.style.objectFit = 'contain';

      isProcessing = true;
      try {
        log('🔍 开始AI识别上传图片...');
        updateStatus('scanning', '⏳', 'AI正在识别...');

        // 直接发送原图（AI不需要预处理）
        const imageDataUrl = canvas.toDataURL('image/jpeg', 0.9);
        const ocrResult = await callOCR(imageDataUrl);
        const text = ocrResult.text || '';

        log(`📄 识别结果: ${text.substring(0, 30)}...`);

        const result = matchTarget(text);
        updateCandidates(result.candidates || []);

        if (result.matched) {
          const infoLine = result.displayInfo ? `\nℹ️ ${result.displayInfo}` : '';
          const displayText = `${result.target}${infoLine}`;
          updateStatus('matched', '✅', '找到匹配！', displayText);
        } else {
          updateStatus('not-matched', '❌', '未找到匹配');
        }
      } catch (e) {
        log('❌ AI识别失败: ' + e.message);
        alert('识别失败: ' + e.message);
      }
      isProcessing = false;
    };

    img.src = URL.createObjectURL(file);
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

document.addEventListener('DOMContentLoaded', init);
