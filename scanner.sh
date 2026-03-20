#!/bin/bash
# 合同扫描器控制脚本
# 用法: ./scanner.sh [start|stop|restart|status|open]

# 动态发现路径（脚本所在目录即项目目录）
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
ADB_CMD="$(command -v adb 2>/dev/null || echo "")"
PORT=8080
PID_FILE="/tmp/contract-scanner.pid"

# 颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

start() {
    if lsof -ti:$PORT > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  服务器已在运行 (端口 $PORT)${NC}"
        return 1
    fi
    
    cd "$APP_DIR"
    nohup python3 server.py > /tmp/scanner.log 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    
    if lsof -ti:$PORT > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 服务器已启动 (端口 $PORT)${NC}"
        echo -e "   本地访问: http://localhost:$PORT"
    else
        echo -e "${RED}❌ 启动失败${NC}"
        return 1
    fi
}

stop() {
    if lsof -ti:$PORT > /dev/null 2>&1; then
        lsof -ti:$PORT | xargs kill 2>/dev/null
        rm -f "$PID_FILE"
        echo -e "${GREEN}✅ 服务器已停止${NC}"
    else
        echo -e "${YELLOW}⚠️  服务器未在运行${NC}"
    fi
}

status() {
    if lsof -ti:$PORT > /dev/null 2>&1; then
        PID=$(lsof -ti:$PORT)
        echo -e "${GREEN}✅ 服务器运行中${NC}"
        echo -e "   PID: $PID"
        echo -e "   端口: $PORT"
        echo -e "   地址: http://localhost:$PORT"
    else
        echo -e "${RED}❌ 服务器未运行${NC}"
    fi
}

open_phone() {
    if ! lsof -ti:$PORT > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  服务器未运行，正在启动...${NC}"
        start
    fi
    
    if [ -n "$ADB_CMD" ]; then
        "$ADB_CMD" reverse tcp:$PORT tcp:$PORT
        echo -e "${GREEN}✅ 已允许手机访问本机 (ADB Reverse)${NC}"
        "$ADB_CMD" shell am start -a android.intent.action.VIEW -d "http://localhost:$PORT?autostart=1" com.android.chrome
        echo -e "${GREEN}✅ 已在Pixel上打开应用${NC}"
    else
        echo -e "${RED}❌ ADB未找到，请确保已安装 Android SDK 且 adb 在 PATH 中${NC}"
    fi
}

open_admin() {
    if ! lsof -ti:$PORT > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  服务器未运行，正在启动...${NC}"
        start
        sleep 1
    fi
    
    echo -e "${GREEN}✅ 正在打开管理面板...${NC}"
    open "http://localhost:$PORT/admin.html"
}

show_help() {
    echo ""
    echo "📱 合同扫描器控制脚本"
    echo ""
    echo "用法: ./scanner.sh [命令]"
    echo ""
    echo "命令:"
    echo "  start   启动服务器"
    echo "  stop    停止服务器"
    echo "  restart 重启服务器"
    echo "  status  查看状态"
    echo "  open    在Pixel手机上打开扫描器"
    echo "  admin   启动并打开管理面板（Mac）"
    echo "  help    显示此帮助"
    echo ""
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 1
        start
        ;;
    status)
        status
        ;;
    open)
        open_phone
        ;;
    admin)
        open_admin
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo ""
        echo "📱 合同扫描器"
        echo ""
        echo "  start   - 启动服务器"
        echo "  stop    - 停止服务器"  
        echo "  restart - 重启服务器"
        echo "  status  - 查看状态"
        echo "  open    - 在手机上打开"
        echo "  admin   - 打开管理面板"
        echo ""
        ;;
esac
