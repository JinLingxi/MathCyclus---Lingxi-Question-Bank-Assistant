# ======================================================================================
# 脚本名称: batch_gen.py
# 功能描述: 
#   1. 从 '说明文档\题目文档.txt' 中批量读取 LaTeX 题目。
#   2. 解析文件名，自动分类存入 'chapters/板块/年份/' 目录。
#   3. 提供交互式覆盖选项 (覆盖/跳过/全部覆盖/全部跳过)。
#   4. 自动修复常见的 LaTeX 格式错误 (如过长的下划线)。
#   5. 记录操作日志到 'log.csv'。
#   6. 自动更新各板块的索引文件 (content_*.tex)，便于 main.tex 调用。
#
# 使用方法:
#   1. 确保 '说明文档\题目文档.txt' 存在且格式正确 (分隔符: ---文件名.tex---)。
#   2. 在项目根目录下运行此脚本: python batch_gen.py
#   3. 根据提示输入 y/n/q/t 来处理同名文件的覆盖问题。
# ======================================================================================

import os
import re
import time
import subprocess
import csv
import datetime

# 基础路径配置
# 项目根目录：脚本运行的工作目录
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
# 源文件路径：存放待处理题目的文本文件
source_file = os.path.join(root_dir, r'说明文档\题目文档.txt')
# 日志文件路径：记录批量处理的操作历史
LOG_FILE = os.path.join(root_dir, 'log.csv')

def parse_filename(filename):
    """
    解析文件名，提取排序所需信息
    
    参数:
        filename (str): 文件名，例如 "2010-G-浙江卷（理）-22-导数.tex"
        
    返回:
        tuple: (year, paper_base, wl_rank, q_num)
            - year (int): 年份，用于按年份分节
            - paper_base (str): 试卷名称（去除文理科标记），用于同一年份内的排序
            - wl_rank (int): 文理科权重（文科=0, 理科=1, 其他=2），用于控制文理科排序顺序
            - q_num (int): 题号，用于同一试卷内的题目排序
    """
    name_body = filename.replace('.tex', '')
    segments = name_body.split('-')
    
    # 默认值初始化，防止解析失败导致报错
    year = 9999
    paper = filename
    q_num = 999
    
    if len(segments) >= 4:
        # 尝试解析年份 (第一段)
        try:
            year = int(segments[0])
        except:
            pass
            
        # 尝试解析题号 (通常在第四段或第五段)
        if len(segments) >= 5:
            paper = segments[2]
            try:
                q_num = int(segments[3])
            except:
                pass
        elif len(segments) == 4:
            paper = segments[2]
            try:
                q_num = int(segments[3])
            except:
                pass

    # 文理科排序处理
    # 逻辑：将文理科标记从试卷名中分离，并赋予权重，确保排序时文科在前或理科在前
    wl_rank = 2
    paper_base = paper
    if '（文）' in paper or '(文)' in paper:
        wl_rank = 0
        paper_base = re.sub(r'[（\(]文[）\)]', '', paper)
    elif '（理）' in paper or '(理)' in paper:
        wl_rank = 1
        paper_base = re.sub(r'[（\(]理[）\)]', '', paper)
        
    return (year, paper_base, wl_rank, q_num)

def update_chapter_contents():
    """
    更新章节索引文件 (content_*.tex)
    
    功能:
        遍历 chapters 目录下的所有板块，为每个板块生成一个汇总的 .tex 文件。
        该文件包含该板块下所有题目的 \input 指令，并按年份分节。
        生成的 content_*.tex 文件可直接在 main.tex 中被调用。
    """
    print("-" * 30)
    print("开始更新章节索引 (content_*.tex)...")
    
    chapters_dir = os.path.join(root_dir, 'chapters')
    if not os.path.exists(chapters_dir):
        print("错误：找不到 chapters 目录")
        return

    # 获取 chapters 下的所有子目录作为板块
    topics = [d for d in os.listdir(chapters_dir) if os.path.isdir(os.path.join(chapters_dir, d))]
    
    print(f"检测到 {len(topics)} 个板块目录: {topics}")

    for topic in topics:
        topic_dir = os.path.join(chapters_dir, topic)
        tex_files = []
        
        # 递归遍历该板块下的所有 .tex 文件
        for root, dirs, files in os.walk(topic_dir):
            # 在遍历前过滤掉名称包含 "相关图" 的文件夹，彻底阻止进入搜索
            dirs[:] = [d for d in dirs if "相关图" not in d]
            
            for file in files:
                if file.endswith('.tex') and not file.startswith('content_'):
                    # 排除 content_*.tex 自身，避免循环引用
                    file_path = os.path.join(root, file)
                    # 计算相对路径，用于 \input 指令
                    rel_path = os.path.relpath(file_path, root_dir)
                    rel_path = rel_path.replace('\\', '/') # 转换为 LaTeX 标准路径分隔符
                    rel_path_no_ext = os.path.splitext(rel_path)[0]
                    
                    tex_files.append({
                        'filename': file,
                        'path': rel_path_no_ext,
                        'sort_key': parse_filename(file)
                    })
        
        if not tex_files:
            print(f"跳过板块 {topic}: 未找到 .tex 题目文件")
            continue
            
        print(f"正在处理板块：{topic} ({len(tex_files)} 题)")
        
        # 根据解析出的 sort_key 进行多级排序
        tex_files.sort(key=lambda x: x['sort_key'])
        
        # 生成 LaTeX 内容
        lines = []
        current_year = None
        
        for item in tex_files:
            # 从 sort_key 中获取年份 (第一个元素)
            year = item['sort_key'][0]
            
            # 添加年份章节（如果年份变化且年份有效）
            if year != current_year and year != 9999:
                lines.append(f"\\section{{{year}}}")
                current_year = year
            
            lines.append(f"\\input{{{item['path']}}}")
            
        # 写入 content_板块名.tex 文件
        output_file = os.path.join(topic_dir, f'content_{topic}.tex')
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"  -> 已生成：{output_file}")
        except Exception as e:
            print(f"  -> 写入失败：{e}")

    print("章节索引更新完成！")
    print("请在 main.tex 中对应的章节下使用 \\input{chapters/板块名/content_板块名.tex} 导入题目。")

def main():
    """
    主程序入口
    """
    start_time = time.time()
    # 生成本次运行的唯一批次 ID，用于日志记录
    batch_id = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_entries = []

    file_path = os.path.join(root_dir, source_file)
    if not os.path.exists(file_path):
        print(f"错误：找不到文件 {file_path}")
        print("请确保您在 'd:\\pc\\Desktop\\Work\\000高中数学题库' 目录下运行此脚本")
        return

    print(f"正在读取文件：{file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 正则分割：利用分隔符切分多个题目
    # 分隔符格式：---文件名.tex---
    # 紧接着是题目内容 \begin{problem} ... \end{problem}
    parts = re.split(r'---(.+\.tex)---\s*', content)

    matches = []
    # parts[0] 是文件开头的说明，跳过
    # 之后的结构是：[文件名1, 内容1, 文件名2, 内容2, ...]
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            filename = parts[i].strip()
            file_content = parts[i+1].strip()
            matches.append((file_content, filename))
    
    created_count = 0
    overwritten_count = 0
    
    # 覆盖模式状态机
    # None: 每次都询问
    # 'all': 全部自动覆盖
    # 'skip': 全部自动跳过
    overwrite_mode = None 

    for file_content, filename in matches:
        filename = filename.strip()
        
        # 解析文件名：2010-G-浙江卷（理）-22-导数.tex
        name_body = filename.replace('.tex', '')
        segments = name_body.split('-')

        # 校验文件名格式是否符合预期 (至少包含年份、类型、试卷名、题号、板块)
        if len(segments) < 5:
            print(f"警告：跳过格式不正确的文件名 {filename}")
            continue

        year = segments[0]       # 年份 (2010)
        topic = segments[-1].split("，")[0]     # 主板块 (处理多标签如: 导数，三角函数)

        # 构建目标路径：chapters/板块/年份/文件名
        target_dir = os.path.join(root_dir, 'chapters', topic, year)
        
        # 自动创建目录 (如果不存在)
        os.makedirs(target_dir, exist_ok=True)
        
        target_path = os.path.join(target_dir, filename)
        
        should_write = False
        status = ""

        # 检查文件是否存在
        if os.path.exists(target_path):
            # 覆盖逻辑判断
            if overwrite_mode == 'skip':
                continue
            elif overwrite_mode == 'all':
                should_write = True
                status = "已覆盖"
            else:
                # 交互式询问用户决策
                print(f"\n发现同名文件: {filename}")
                print(f"路径: {target_path}")
                while True:
                    choice = input("是否覆盖? [y:是 / n:否 / q:剩余全不覆盖 / t:剩余全覆盖]: ").strip().lower()
                    if choice == 'y':
                        should_write = True
                        status = "已覆盖"
                        break
                    elif choice == 'n':
                        should_write = False
                        print(f"[保留] {filename}")
                        break
                    elif choice == 'q':
                        overwrite_mode = 'skip'
                        should_write = False
                        print(">> 已切换模式：后续所有重复文件均不覆盖")
                        break
                    elif choice == 't':
                        overwrite_mode = 'all'
                        should_write = True
                        status = "已覆盖"
                        print(">> 已切换模式：后续所有重复文件均自动覆盖")
                        break
            
            if should_write:
                try:
                    os.remove(target_path) # 先删除旧文件
                    overwritten_count += 1
                except Exception as e:
                    print(f"删除文件失败: {target_path}, 错误: {e}")
                    should_write = False
        else:
            status = "已新建"
            created_count += 1
            should_write = True

        if should_write:
            # 自动修复常见格式错误
            # 1. 将连续的4个及以上下划线替换为填空横线 \underline{\hspace{4em}}
            #    避免 LaTeX 将其识别为数学下标导致 "Missing $ inserted" 错误
            file_content = re.sub(r'_{4,}', r'\\underline{\\hspace{4em}}', file_content)

            # 写入文件
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
            print(f"[{status}] {target_path}")
            
            # 将操作记录添加到日志缓存
            log_entries.append({
                'BatchID': batch_id,
                'Timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'Action': status,
                'FileName': filename,
                'FilePath': target_path
            })

    # 将日志写入文件
    if log_entries:
        file_exists = os.path.isfile(LOG_FILE)
        try:
            with open(LOG_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['BatchID', 'Timestamp', 'Action', 'FileName', 'FilePath']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerows(log_entries)
            print(f"日志已写入：{LOG_FILE}")
        except Exception as e:
            print(f"写入日志失败：{e}")

    end_time = time.time()
    duration = end_time - start_time
    
    print(f"\n{'='*30}")
    print(f"处理完成！")
    print(f"共新建文件：{created_count} 个")
    print(f"共覆盖文件：{overwritten_count} 个")
    print(f"总耗时：{duration:.2f} 秒")
    print(f"{'='*30}")

    # 最后更新章节索引
    update_chapter_contents()

if __name__ == '__main__':
    main()