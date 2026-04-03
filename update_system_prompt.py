"""
更新 system prompt，添加推荐问题生成指令
"""

SUGGESTED_QUESTIONS_INSTRUCTION = """

在每次回复的最后，请生成 4 个用户可能感兴趣的后续问题。
使用以下格式（必须严格遵守）：

---SUGGESTED_QUESTIONS---
1. 问题文本1
2. 问题文本2
3. 问题文本3
4. 问题文本4
---END_SUGGESTED_QUESTIONS---

要求：
- 问题要基于当前对话内容，具有针对性
- 问题长度控制在 15-30 字
- 涵盖不同维度（事业、感情、健康、财运等）
- 使用疑问句形式
"""

if __name__ == "__main__":
    print("请手动执行以下步骤来更新 system prompt：")
    print("\n1. 登录到管理后台：http://localhost:3000/admin/config/system_prompt")
    print("\n2. 在现有 system prompt 的末尾添加以下内容：")
    print("=" * 60)
    print(SUGGESTED_QUESTIONS_INSTRUCTION)
    print("=" * 60)
    print("\n3. 保存并测试")
