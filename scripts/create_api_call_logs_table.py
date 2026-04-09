"""
创建 api_call_logs 表
用法: python scripts/create_api_call_logs_table.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import engine, Base
from app.models.api_call_log import ApiCallLog  # noqa: F401 确保模型被导入

def main():
    print("Creating api_call_logs table...")
    Base.metadata.create_all(bind=engine, tables=[ApiCallLog.__table__])
    print("Done! Table api_call_logs created.")

if __name__ == "__main__":
    main()
