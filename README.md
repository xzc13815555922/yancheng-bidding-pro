# 盐城市全域招标信息采集系统 Pro

盐城市全域12个招标网站的数据采集、清洗、富化、分类和导出系统。

## 覆盖站点

| 站点 | 说明 |
|------|------|
| jszbcg | 江苏招标采购服务平台（盐城） |
| jingkai | 盐城经开区 |
| kaifaqu | 盐城开发区 |
| ycggzy | 盐城公共资源交易 |
| yancheng_gov | 盐城政府网 |
| bigdata | 大数据平台 |
| chennan | 盐南高新区 |
| dongfang | 东方招标 |
| dushi | 都市招标 |
| jscn | 江苏城南 |
| sufu | 苏服务 |
| yueda | 悦达 |

## 目录结构

```
crawlers/          各站点爬虫
  base.py          基类
  jszbcg.py        江苏招标采购服务平台
  ...
add_std_category.py   标准分类打标（proj_major_cat / proj_minor_cat）
add_std_district.py   行政区划打标
enrich_details.py     详情页富化
enrich_jszbcg_ocr.py  PDF OCR 富化（PaddleOCR）
export_excel.py       导出 Excel
run_collection.py     采集入口
run_daily.sh          每日自动化脚本（凌晨2点全流程）
```

## 依赖

```bash
pip install requests pymupdf paddleocr openpyxl
```

## 运行

```bash
# 单次采集（最近3天）
python3 run_collection.py --days 3

# 富化详情页
python3 enrich_details.py

# OCR 补全（图片型PDF）
python3 enrich_jszbcg_ocr.py

# 分类打标
python3 add_std_category.py

# 导出 Excel
python3 export_excel.py

# 全流程（每日自动化）
bash run_daily.sh
```

## 分类体系

`proj_major_cat` / `proj_minor_cat` 两级分类，反向过滤策略：
先标注不相关类别（物业/市政/法律/劳务/车辆/设计等），未标注的即为信息化商机池。
