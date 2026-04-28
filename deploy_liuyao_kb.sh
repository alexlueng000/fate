#!/bin/bash
# 六爻知识库部署脚本
# 用途：重组知识库目录结构，将八字和六爻知识库分离

set -e

echo "=========================================="
echo "六爻知识库部署脚本"
echo "=========================================="

# 1. 创建新的目录结构
echo ""
echo "[1/5] 创建目录结构..."
mkdir -p kb_files/bazi
mkdir -p kb_files/liuyao
mkdir -p kb_index/bazi
mkdir -p kb_index/liuyao

# 2. 移动现有八字知识库文件
echo ""
echo "[2/5] 移动八字知识库文件..."
if [ -f "kb_files/knowladge1.docx" ]; then
    mv kb_files/knowladge*.docx kb_files/bazi/ 2>/dev/null || true
    mv kb_files/knowladge*.txt kb_files/bazi/ 2>/dev/null || true
    echo "  ✓ 八字源文件已移动到 kb_files/bazi/"
else
    echo "  ⚠ 未找到八字源文件（可能已移动）"
fi

# 3. 移动现有八字索引
echo ""
echo "[3/5] 移动八字索引文件..."
if [ -f "kb_index/chunks.json" ]; then
    mv kb_index/chunks.json kb_index/bazi/ 2>/dev/null || true
    mv kb_index/embeddings.npz kb_index/bazi/ 2>/dev/null || true
    mv kb_index/metadata.json kb_index/bazi/ 2>/dev/null || true
    echo "  ✓ 八字索引已移动到 kb_index/bazi/"
else
    echo "  ⚠ 未找到八字索引（可能已移动）"
fi

# 4. 检查六爻知识库文件
echo ""
echo "[4/5] 检查六爻知识库文件..."
if [ -f "kb_files/liuyao/Divination.txt" ]; then
    echo "  ✓ 六爻知识库文件已存在"
else
    echo "  ✗ 错误：未找到 kb_files/liuyao/Divination.txt"
    echo "  请确保该文件已创建"
    exit 1
fi

# 5. 构建六爻知识库索引
echo ""
echo "[5/5] 构建六爻知识库索引..."
echo "  执行命令: python kb_rag_mult.py kb_files/liuyao kb_index/liuyao"
python kb_rag_mult.py kb_files/liuyao kb_index/liuyao

# 验证索引文件
if [ -f "kb_index/liuyao/chunks.json" ]; then
    echo "  ✓ 六爻索引构建成功"
else
    echo "  ✗ 错误：索引构建失败"
    exit 1
fi

# 完成
echo ""
echo "=========================================="
echo "部署完成！"
echo "=========================================="
echo ""
echo "目录结构："
echo "  kb_files/"
echo "    ├── bazi/          # 八字知识库源文件"
echo "    └── liuyao/        # 六爻知识库源文件"
echo ""
echo "  kb_index/"
echo "    ├── bazi/          # 八字索引"
echo "    └── liuyao/        # 六爻索引"
echo ""
echo "下一步："
echo "  1. 重启后端服务: systemctl restart fate-api"
echo "  2. 测试解卦功能"
echo ""
