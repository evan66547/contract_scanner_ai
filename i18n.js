const i18nDict = {
    en: {
        // Shared
        "status.error": "⚠️ System Error",
        "status.loading": "Loading...",
        "btn.close": "Close",
        "btn.cancel": "Cancel",
        "btn.confirm": "Confirm",
        
        // index.html
        "app.title": "Contract Scanner",
        "app.start": "Tap to Start Scanning",
        "app.pause": "Pause",
        "app.resume": "Resume",
        "app.candidates": "Possible Matches",
        "app.camera_req": "Camera Permission Required",
        "app.camera_hint": "Please allow camera access in your browser settings\\n\\nRefresh page to try again",
        "app.camera_missing": "Camera Not Found",
        "app.camera_missing_hint": "Please ensure your device has an available camera",
        "app.ws_disconnected": "Connection Lost",
        "app.ws_refresh": "Please refresh page to reconnect",
        "app.scanning": "Scanning...",
        "app.not_target": "Not Target Object",
        "app.match_found": "✅ Match Found!",
        "app.additional_info": "🔖 This object contains additional info",
        "app.info_prefix": "👉 Additional Info:\\n",
        
        // admin.html
        "admin.title": "Scanner AI - Control Panel",
        "admin.header": "Control Panel",
        "admin.subtitle": "Manage your target list and application settings",
        "admin.card.import": "Target List Import",
        "admin.card.ai": "AI Core Settings",
        "admin.card.camera": "Camera & UI",
        "admin.card.actions": "Actions",
        "admin.card.sys": "System Status",
        
        "admin.upload.hint": "Drop Excel / CSV file here",
        "admin.upload.or": "or",
        "admin.upload.browse": "Browse files",
        "admin.upload.template": "📥 Download Template",
        
        "admin.stats.total": "Total tracked objects:",
        "admin.btn.view": "👁️ View List",
        "admin.btn.test": "🎯 Open Phone Scanner",
        
        "admin.settings.interval": "Recognition Interval (ms)",
        "admin.settings.tolerance": "Match Tolerance",
        "admin.settings.distance": "Levenshtein Distance:",
        "admin.settings.show_overlay": "Show Scanning Overlay",
        "admin.settings.show_debug": "Show Debug Dashboard",
        "admin.settings.save": "💾 Save Settings",
        
        "admin.status.db": "Database:",
        "admin.status.db_count": "items",
        "admin.status.engine": "GLM Engine:",
        "admin.status.engine_ok": "Ready",
        
        "admin.import.summary": "Total items:",
        "admin.import.manual_name": "Target Column",
        "admin.import.manual_info": "Info Col (Opt)",
        "admin.import.btn_remap": "🔄 Remap",
        "admin.import.table_idx": "#",
        "admin.import.table_name": "Target Name",
        "admin.import.table_info": "Display Info",
        "admin.import.btn_cancel": "Cancel",
        "admin.import.btn_confirm": "Confirm Import",
        
        "admin.view.title": "Current recognized object records:",
        
        // NEW ADMIN KEYS
        "admin.lbl.interval": "AI Scan Interval (ms)",
        "admin.lbl.res": "Camera Resolution",
        "admin.lbl.ratio": "Min Match Ratio",
        "admin.lbl.prefix": "Require Prefix Match",
        "admin.lbl.length": "Min Keyword Length",
        "admin.lbl.distance": "Levenshtein Tolerance",
        "admin.lbl.roix": "ROI X",
        "admin.lbl.roiy": "ROI Y",
        "admin.lbl.roiw": "ROI Width",
        "admin.lbl.roih": "ROI Height",
        "admin.lbl.show_log": "Show Debug Log",
        "admin.lbl.show_overlay": "Show Overlay on Phone",
        "admin.stat.server": "Server",
        "admin.stat.engine": "AI Engine",
        "admin.stat.fps": "Scan FPS",
        "admin.stat.running": "Running",
        "admin.card.roi": "Recognition ROI",
        "admin.card.debug": "Debug Options",
        "admin.card.about": "About System",
        "admin.btn.open_scanner": "Open Scanner",
        "admin.btn.refresh": "Refresh Panel",
        "admin.btn.template": "Template",
        "admin.btn.view_list": "View List",
        "admin.btn.select_file": "Select File",
        "admin.btn.cancel": "Cancel",
        "admin.btn.confirm": "Confirm Import",
        "admin.btn.remap": "Remap Columns",
        "admin.btn.save": "Save & Apply Config",
        "admin.dz.sub": "Supports .xlsx .xls .csv",

        "admin.desc.interval": "Recommended >= 1500ms for AI inference",
        "admin.desc.ratio": "Require matching X% of target characters",
        "admin.desc.prefix": "Must include the starting part of target name",
        "admin.desc.length": "Minimum N chars to prevent misfires",
        "admin.desc.distance": "Tolerance for added/omitted/wrong chars",
        "admin.info.ai_title": "AI Mode Note:",
        "admin.info.ai_desc": "GLM-OCR directly interprets raw images without traditional binarization. High perf required, interval 1500ms+ is recommended.",
        "admin.info.tip_title": "Tip:",
        "admin.info.tip_desc": "With high AI accuracy and fewer typos, you can increase match ratio to 70%.",
        "admin.info.roi_title": "Feature Note:",
        "admin.info.roi_desc": "The green box is the actual cropped area sent to AI. Narrowing it speeds up OCR significantly.",
        "admin.about.ocr": "OCR Engine:",
        "admin.about.ocr_val": "GLM-OCR 0.9B (Zhipu AI Vision Model)",
        "admin.about.engine": "Inference Engine:",
        "admin.about.engine_val": "Ollama (Apple Metal GPU Accel)",
        "admin.about.alg": "Matching Algorithm:",
        "admin.about.alg_val": "Keyword / Prefix / Levenshtein Distance",
        "admin.about.db": "Built-in Data:",
        "admin.about.db_val": "targets tracked",

        // dynamic messages
        "msg.save_success": "✅ Saved! Refresh phone to apply.",
        "msg.save_fail": "❌ Save failed: ",
        "msg.unsupported_file": "❌ Unsupported format, use .xlsx or .csv",
        "msg.parsing": "📊 Parsing...",
        "msg.parse_ok": "✅ Parsed successfully, please confirm",
        "msg.parse_fail": "❌ Parsing failed: ",
        "msg.select_col": "⚠️ Please select the Target Column first",
        "msg.importing": "💾 Importing...",
        "msg.import_ok": "✅ Successfully imported!",
        "msg.import_fail": "❌ Import failed: ",
        "msg.opening_phone": "📱 Opening scanner on phone...",
        "msg.view_fail": "❌ Failed to load imported data: ",
        "msg.empty": "Empty",
        "msg.none": "-- None --",
        "msg.select": "-- Select --"
    },
    zh: {
        // Shared
        "status.error": "⚠️ 系统错误",
        "status.loading": "正在加载...",
        "btn.close": "关闭",
        "btn.cancel": "取消",
        "btn.confirm": "确认",
        
        // index.html
        "app.title": "合同扫描器",
        "app.start": "点击开始识别",
        "app.pause": "暂停",
        "app.resume": "继续",
        "app.candidates": "疑似匹配",
        "app.camera_req": "需要摄像头权限",
        "app.camera_hint": "请在浏览器设置中允许访问摄像头\\n\\n刷新页面重试",
        "app.camera_missing": "未找到摄像头",
        "app.camera_missing_hint": "请确保设备有可用的摄像头",
        "app.ws_disconnected": "连接已断开",
        "app.ws_refresh": "请刷新页面重新连接",
        "app.scanning": "正在识别...",
        "app.not_target": "非目标对象",
        "app.match_found": "✅ 找到匹配！",
        "app.additional_info": "🔖 此对象包含附加信息",
        "app.info_prefix": "👉 附加信息：\\n",
        
        // admin.html
        "admin.title": "合同扫描器 AI版 - 控制面板",
        "admin.header": "控制面板",
        "admin.subtitle": "管理识别目标名单与高级应用设置",
        "admin.card.import": "识别名单导入",
        "admin.card.ai": "AI 核心设置",
        "admin.card.camera": "界面与扫描控制",
        "admin.card.actions": "全局指令",
        "admin.card.sys": "系统状态",
        
        "admin.upload.hint": "将 Excel / CSV 文件拖到此处",
        "admin.upload.or": "或",
        "admin.upload.browse": "浏览文件",
        "admin.upload.template": "📥 下载导入模板",
        
        "admin.stats.total": "当前已追踪目标数目：",
        "admin.btn.view": "👁️ 查看名单",
        "admin.btn.test": "🎯 手机上打开扫描器",
        
        "admin.settings.interval": "图像截取频率 (ms)",
        "admin.settings.tolerance": "名称匹配容错度",
        "admin.settings.distance": "允许的汉字编辑距离：",
        "admin.settings.show_overlay": "显示扫描框遮罩",
        "admin.settings.show_debug": "显示开发者调试面板",
        "admin.settings.save": "💾 保存当前设置",
        
        "admin.status.db": "数据库:",
        "admin.status.db_count": "条",
        "admin.status.engine": "GLM 引擎:",
        "admin.status.engine_ok": "就绪",
        
        "admin.import.summary": "共计：",
        "admin.import.manual_name": "识别对象列",
        "admin.import.manual_info": "显示信息列(可选)",
        "admin.import.btn_remap": "🔄 重新映射",
        "admin.import.table_idx": "#",
        "admin.import.table_name": "识别对象",
        "admin.import.table_info": "显示信息",
        "admin.import.btn_cancel": "取消导入",
        "admin.import.btn_confirm": "确认并替换旧名单",
        
        "admin.view.title": "当前共有记录：",
        
        // NEW ADMIN KEYS
        "admin.lbl.interval": "图像截取频率 (ms)",
        "admin.lbl.res": "摄像头分辨率",
        "admin.lbl.ratio": "最小匹配比例",
        "admin.lbl.prefix": "要求前缀匹配",
        "admin.lbl.length": "最小关键词长度",
        "admin.lbl.distance": "编辑距离容忍度",
        "admin.lbl.roix": "横向位置",
        "admin.lbl.roiy": "纵向位置",
        "admin.lbl.roiw": "选取宽度",
        "admin.lbl.roih": "选取高度",
        "admin.lbl.show_log": "显示运行调试日志",
        "admin.lbl.show_overlay": "在手机显示扫描框",
        "admin.stat.server": "服务端",
        "admin.stat.engine": "AI 引擎",
        "admin.stat.fps": "扫描频率",
        "admin.stat.running": "运行中",
        "admin.card.roi": "提取识别区域",
        "admin.card.debug": "调试选项",
        "admin.card.about": "关于系统",
        "admin.btn.open_scanner": "打开扫描器",
        "admin.btn.refresh": "刷新面板",
        "admin.btn.template": "下载模板",
        "admin.btn.view_list": "查看名单",
        "admin.btn.select_file": "选择文件",
        "admin.btn.cancel": "取消",
        "admin.btn.confirm": "确认导入",
        "admin.btn.remap": "重新映射",
        "admin.btn.save": "保存并应用系统配置",
        "admin.dz.sub": "支持 .xlsx .xls .csv",

        "admin.desc.interval": "推荐 1500ms+，AI 需要推理时间",
        "admin.desc.ratio": "要求匹配目标名称的X%字符",
        "admin.desc.prefix": "必须包含目标名称开头部分",
        "admin.desc.length": "至少N个字才触发匹配以防误触",
        "admin.desc.distance": "多加字/漏字等容忍差异数量",
        "admin.info.ai_title": "AI 模式说明：",
        "admin.info.ai_desc": "GLM-OCR 直接理解原始图片，无需二值化等传统预处理。要求机器性能极高，扫描间隔建议 ≥1500ms。",
        "admin.info.tip_title": "提示：",
        "admin.info.tip_desc": "AI 识别精度大幅提升后错字极少，匹配比例可提高至 70%。",
        "admin.info.roi_title": "功能提示：",
        "admin.info.roi_desc": "绿色框即为实际发送给 AI 的截图区域。通过缩窄区域可大幅加快 OCR 识别。",
        "admin.about.ocr": "OCR 引擎：",
        "admin.about.ocr_val": "GLM-OCR 0.9B (智谱AI视觉模型)",
        "admin.about.engine": "推理引擎：",
        "admin.about.engine_val": "Ollama (Apple Metal GPU加速)",
        "admin.about.alg": "匹配算法：",
        "admin.about.alg_val": "结合拼音短名/前缀命中/编辑距离",
        "admin.about.db": "内置资料：",
        "admin.about.db_val": "份对象数据",

        // dynamic messages
        "msg.save_success": "✅ 保存成功！请刷新手机页面生效。",
        "msg.save_fail": "❌ 保存失败: ",
        "msg.unsupported_file": "❌ 不支持的文件格式，请使用 .xlsx 或 .csv",
        "msg.parsing": "📊 正在解析...",
        "msg.parse_ok": "✅ 解析成功，请确认导入",
        "msg.parse_fail": "❌ 解析失败: ",
        "msg.select_col": "⚠️ 请先选择识别对象列",
        "msg.importing": "💾 正在导入...",
        "msg.import_ok": "✅ 成功导入新名单！旧数据已备份。",
        "msg.import_fail": "❌ 导入失败: ",
        "msg.opening_phone": "📱 正在手机上打开扫描器...",
        "msg.view_fail": "❌ 加载已导入数据失败: ",
        "msg.empty": "空",
        "msg.none": "-- 无 --",
        "msg.select": "-- 请选择 --"
    }
};

let currentLang = localStorage.getItem('lang') || 'en';

function t(key) {
    if (!i18nDict[currentLang] || !i18nDict[currentLang][key]) {
        return key; 
    }
    // Handle literal \n for JS multi-lines if needed depending on usage
    return i18nDict[currentLang][key];
}

function switchLang() {
    currentLang = currentLang === 'en' ? 'zh' : 'en';
    localStorage.setItem('lang', currentLang);
    applyI18n();
    if (typeof window.onLangChanged === 'function') {
        window.onLangChanged();
    }
}

function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        const translated = t(key);
        
        if (el.tagName === 'INPUT' && (el.type === 'button' || el.type === 'submit')) {
            el.value = translated;
        } else if (el.tagName === 'INPUT' && el.placeholder) {
            el.placeholder = translated;
        } else {
            // Check if it has child elements (e.g. icons). If so, text replacement is trickier.
            // In our app, we usually put text in span or leaf nodes.
            // If there's an icon, we'll let [data-i18n] on a <span> inside handle the text.
            el.textContent = translated;
        }
    });

    const langBtn = document.getElementById('lang-toggle');
    if (langBtn) {
        langBtn.textContent = currentLang === 'en' ? '🇨🇳 中文' : '🇬🇧 EN';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    applyI18n();
});
