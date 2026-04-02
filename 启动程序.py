import os
import sys
import subprocess
import time
import platform

def kill_existing_streamlit():
    """精确终止当前题库应用对应的 Streamlit 进程"""
    print("正在检查并清理残留的题库进程...")
    try:
        # 获取当前应用的唯一标识（脚本名）
        target_script = "question_bank_app.py"
        
        if platform.system() == "Windows":
            # 使用 wmic 精确查找包含 target_script 的 python 或 streamlit 进程
            find_cmd = f'wmic process where "name like \'%python%\' and commandline like \'%{target_script}%\'" get processid'
            result = subprocess.run(find_cmd, shell=True, capture_output=True, text=True)
            
            pids = []
            for line in result.stdout.strip().split('\n')[1:]: # 跳过表头
                pid_str = line.strip()
                if pid_str.isdigit():
                    pids.append(pid_str)
            
            current_pid = str(os.getpid())
            killed_count = 0
            for pid in pids:
                if pid != current_pid: # 不要杀掉当前的启动脚本本身
                    print(f"找到残留题库进程 (PID: {pid})，正在终止...")
                    subprocess.run(['taskkill', '/F', '/PID', pid, '/T'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    killed_count += 1
            
            if killed_count == 0:
                print("未发现残留进程，环境干净。")
        else:
            # 对于 Linux/Mac
            subprocess.run(['pkill', '-f', f'streamlit.*{target_script}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"清理进程时出现警告 (可忽略): {e}")

def main():
    # 设置控制台标题 (仅 Windows)
    if os.name == 'nt':
        os.system('title 高中数学题库管理助手')
    
    # 切换到脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    print("========================================================")
    print("          高中数学题库管理助手 (Math Question Bank)")
    print("========================================================")
    print()
    print("[1/3] 正在初始化环境...")
    
    # 精确终止当前题库的旧进程
    kill_existing_streamlit()
    
    print("[2/3] 启动 Streamlit 服务...")
    print()
    print("浏览器即将自动打开...")
    print("如需关闭程序，请直接关闭此命令行窗口 (Ctrl+C)。")
    print()

    # 构建启动命令
    # 优先尝试直接运行 streamlit
    cmd = ["streamlit", "run", "question_bank_app.py"]
    
    try:
        # 使用 subprocess 启动，并在当前环境运行
        # shell=True 在 Windows 上可以避免一些路径问题，但这里主要依靠 PATH
        subprocess.run(cmd, check=True, shell=(os.name == 'nt'))
    except subprocess.CalledProcessError:
        print()
        print("尝试使用 python -m streamlit 启动...")
        try:
            cmd = [sys.executable, "-m", "streamlit", "run", "question_bank_app.py"]
            subprocess.run(cmd, check=True, shell=(os.name == 'nt'))
        except subprocess.CalledProcessError:
            print()
            print("[错误] 启动失败。")
            print("请确认已安装 streamlit (pip install streamlit)")
            input("按回车键退出...")
    except FileNotFoundError:
        print()
        print("未找到 streamlit 命令，尝试使用 python -m 方式...")
        try:
            cmd = [sys.executable, "-m", "streamlit", "run", "question_bank_app.py"]
            subprocess.run(cmd, check=True, shell=(os.name == 'nt'))
        except Exception as e:
            print()
            print(f"[错误] 启动失败: {e}")
            input("按回车键退出...")
    except KeyboardInterrupt:
        print("\n程序已关闭。")

if __name__ == "__main__":
    main()