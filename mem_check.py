import os, psutil

process = psutil.Process(os.getpid())

for i in range(1_000_000):
    if i % 100_000 == 0:  # 每10万次打印一次
        mem = process.memory_info().rss / 1024 / 1024
        print(f"第 {i:,} 次，内存占用：{mem:.2f} MB")

print("完成！")
