"""
更新 system prompt，添加推荐问题生成指令
"""

SUGGESTED_QUESTIONS_INSTRUCTION = """

# 追问

在每次回复的最后，请生成 4 个用户可能感兴趣的后续问题。
使用以下格式（必须严格遵守，特别是结束标记）：

---SUGGESTED_QUESTIONS---
1. 问题文本1
2. 问题文本2
3. 问题文本3
4. 问题文本4
---END_SUGGESTED_QUESTIONS---

重要提示：
- 结束标记必须完整输出 ---END_SUGGESTED_QUESTIONS---（不能只输出 ---）
- 问题要基于当前对话内容，具有针对性
- 问题长度控制在 15-30 字
- 涵盖不同维度（事业、感情、健康、财运等）
- 使用疑问句形式

示例：
---SUGGESTED_QUESTIONS---
1. 我的事业运势如何？
2. 今年财运怎么样？
3. 感情方面有什么建议？
4. 如何提升运势？
---END_SUGGESTED_QUESTIONS---
"""

if __name__ == "__main__":
    print("请手动执行以下步骤来更新 system prompt：")
    print("\n1. 登录到管理后台：http://localhost:3000/admin/config/system_prompt")
    print("\n2. 在现有 system prompt 的末尾添加以下内容：")
    print("=" * 60)
    print(SUGGESTED_QUESTIONS_INSTRUCTION)
    print("=" * 60)
    print("\n3. 保存并测试")
    print("\n注意：确保结束标记 ---END_SUGGESTED_QUESTIONS--- 完整输出")
