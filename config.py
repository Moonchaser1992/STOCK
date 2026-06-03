"""选股系统集中配置"""
import os

# --- 项目路径 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
RESULTS_DIR = os.path.join(DATA_DIR, "results")

# --- 市场范围 ---
# 创业板: 300xxx, 301xxx; 科创板: 688xxx; 北交所: 8xxxxx (bj前缀)
ALLOWED_BOARD_PREFIXES = ("300", "301", "688", "8")

# --- 基础过滤 ---
MAX_MARKET_CAP_YI = 400  # 总市值 < 400亿(单位:亿元)
MIN_LISTING_DAYS = 100    # 上市天数 >= 100

# --- 初筛排名 ---
RANK_TOP_N = 30  # 每种排序选前N名
RANK_PERIODS = {
    "1d": 1,
    "5d": 5,
    "10d": 10,
}

# --- 量价形态 ---
VP_WINDOW_MIN = 10  # 量价形态观察窗口最小交易日
VP_WINDOW_MAX = 15  # 量价形态观察窗口最大交易日
VP_VOLUME_RATIO = 1.3  # 前半段均量需大于后半段均量的倍数

# --- 涨停成交量修正 ---
LIMIT_UP_RATIO_BJ = 0.30   # 北交所涨停幅度
LIMIT_UP_RATIO_OTHER = 0.20  # 创业板/科创板涨停幅度
LIMIT_UP_VOLUME_MIN_RATIO = 0.6  # 涨停日量低于近5日均量的60%时触发修正

# --- 微信推送 ---
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

# --- Git ---
GIT_AUTO_SYNC = True
