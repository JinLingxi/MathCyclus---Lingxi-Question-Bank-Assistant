import json
import datetime

def generate_heatmap_html(daily_activity):
    today = datetime.date.today()
    # 从 2026-01-01 开始计算
    start_date = datetime.date(2026, 1, 1)
    
    # 如果今天还没到2026年，或者就是为了展示全年的效果，可以固定到今天，但为了遵循“从2026年1月1日开始”
    # 我们可以计算到今年年底，或者就是计算到今天（但起点是2026-01-01）
    if today < start_date:
        today = datetime.date(2026, 12, 31) # 如果系统时间不对，默认展示2026一整年
        
    start_sunday = start_date - datetime.timedelta(days=(start_date.weekday() + 1) % 7)
    
    weeks = []
    current_date = start_sunday
    while current_date <= today:
        week = []
        for _ in range(7):
            if current_date < start_date or current_date > today:
                week.append(None)
            else:
                week.append(current_date)
            current_date += datetime.timedelta(days=1)
        weeks.append(week)
        
    months_html = '<div style="display: flex; font-size: 14px; color: #8b949e; height: 20px; align-items: flex-end; padding-bottom: 4px;">'
    current_month = None
    for week in weeks:
        day = next((d for d in week if d is not None), None)
        if day and day.month != current_month:
            months_html += f'<div style="width: 18px; overflow: visible; white-space: nowrap; color: #8b949e;">{day.strftime("%b")}</div>'
            current_month = day.month
        else:
            months_html += f'<div style="width: 18px;"></div>'
    months_html += '</div>'
    
    grid_html = '<div class="heatmap-grid">'
    for week in weeks:
        grid_html += '<div class="heatmap-col">'
        for day in week:
            if day is None:
                grid_html += '<div class="heatmap-cell hidden"></div>'
            else:
                date_str = day.isoformat()
                count = daily_activity.get(date_str, 0)
                if count == 0: level = 0
                elif count <= 2: level = 1
                elif count <= 5: level = 2
                elif count <= 10: level = 3
                else: level = 4
                
                if count > 0:
                    title = f"{date_str} 录入/修改了 {count} 次题目"
                else:
                    title = f"{date_str} 无记录"
                grid_html += f'<div class="heatmap-cell" data-level="{level}" title="{title}"></div>'
        grid_html += '</div>'
    grid_html += '</div>'
    
    html = f"""
    <style>
    .heatmap-container {{
        display: flex;
        flex-direction: column;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        background:
            radial-gradient(circle at 92% 8%, rgba(124, 58, 237, 0.10), transparent 12rem),
            linear-gradient(180deg, rgba(249, 250, 255, 0.96) 0%, rgba(235, 241, 251, 0.94) 100%);
        color: #263241;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid rgba(96, 125, 170, 0.18);
        box-shadow: 0 14px 34px rgba(31, 35, 48, 0.08);
        width: 100%;
        height: 300px;
        box-sizing: border-box;
        overflow: hidden;
        margin-bottom: 0px;
        transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
        animation: chartFadeUp 0.4s ease both;
    }}
    @keyframes chartFadeUp {{
        from {{ opacity: 0; transform: translateY(8px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}
    .heatmap-container:hover {{
        transform: translateY(-2px);
        border-color: rgba(96, 125, 170, 0.28);
        box-shadow: 0 18px 44px rgba(31, 35, 48, 0.12);
    }}
    /* 美化内部滚动条 */
    .heatmap-scroll-area {{
        display: flex;
        flex: 1;
        overflow-x: auto;
        overflow-y: hidden;
        padding-top: 35px; /* 为 tooltip 预留顶部空间 */
        padding-bottom: 5px; /* 给滚动条留出空间 */
    }}
    .heatmap-scroll-area::-webkit-scrollbar {{
        height: 8px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-track {{
        background: rgba(148, 163, 184, 0.16);
        border-radius: 4px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-thumb {{
        background: rgba(100, 116, 139, 0.46);
        border-radius: 4px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-thumb:hover {{
        background: rgba(71, 85, 105, 0.62);
    }}
    .heatmap-title {{
        font-size: 18px;
        font-weight: 600;
        margin-bottom: -10px; /* 减小标题自带的底部边距，依靠 scroll-area 的 padding-top 撑开 */
        color: #263241;
    }}
    .heatmap-grid {{
        display: flex;
        gap: 4px;
    }}
    .heatmap-col {{
        display: flex;
        flex-direction: column;
        gap: 4px;
    }}
    .heatmap-cell {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
        background-color: rgba(148, 163, 184, 0.32);
        position: relative;
        transition: transform 0.12s ease, box-shadow 0.12s ease;
    }}
    .heatmap-cell:not(.hidden):hover {{
        transform: scale(1.18);
        box-shadow: 0 0 0 2px rgba(255,255,255,0.18);
    }}
    .heatmap-cell[data-level="1"] {{ background-color: #86efac; }}
    .heatmap-cell[data-level="2"] {{ background-color: #4ade80; }}
    .heatmap-cell[data-level="3"] {{ background-color: #22c55e; }}
    .heatmap-cell[data-level="4"] {{ background-color: #16a34a; }}
    .heatmap-cell.hidden {{ background-color: transparent; pointer-events: none; }}
    
    .heatmap-footer {{
        display: flex;
        justify-content: flex-end;
        width: 100%;
        margin-top: 10px;
        font-size: 14px;
        color: #64748b;
        align-items: center;
    }}
    .legend {{
        display: flex;
        align-items: center;
        gap: 4px;
    }}
    .legend-cell {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
    }}
    .heatmap-cell:hover::after {{
        content: attr(title);
        position: absolute;
        bottom: 100%;
        left: 50%;
        transform: translateX(-50%);
        background-color: rgba(0, 0, 0, 0.8);
        color: #fff;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 14px;
        white-space: nowrap;
        z-index: 9999; /* 提高层级，防止被月份栏遮挡 */
        pointer-events: none;
        margin-bottom: 5px;
    }}
    </style>
    <div class="heatmap-container">
        <div class="heatmap-title">🗓️ 活跃指标 (Active Days)</div>
        <div class="heatmap-scroll-area">
            <div style="display: flex; flex-direction: column; gap: 4px; font-size: 14px; color: #64748b; margin-right: 8px; margin-top: 20px; position: sticky; left: 0; background-color: rgba(249,250,255,0.96); z-index: 2;">
                <div style="height: 14px;"></div>
                <div style="height: 14px; line-height: 14px;">M</div>
                <div style="height: 14px;"></div>
                <div style="height: 14px; line-height: 14px;">W</div>
                <div style="height: 14px;"></div>
                <div style="height: 14px; line-height: 14px;">F</div>
                <div style="height: 14px;"></div>
            </div>
            <div>
                {months_html}
                {grid_html}
            </div>
        </div>
        <div class="heatmap-footer">
            <div class="legend">
                Less
                <div class="legend-cell" style="background-color: rgba(148, 163, 184, 0.32);"></div>
                <div class="legend-cell" style="background-color: #86efac;"></div>
                <div class="legend-cell" style="background-color: #4ade80;"></div>
                <div class="legend-cell" style="background-color: #22c55e;"></div>
                <div class="legend-cell" style="background-color: #16a34a;"></div>
                More
            </div>
        </div>
    </div>
    """
    return html

def _generate_activity_curve_html_legacy(hourly_activity_by_day):
    today = datetime.date.today()
    days_data = []
    for i in range(7):
        d = today - datetime.timedelta(days=i)
        date_str = d.isoformat()
        if i == 0:
            label = "今天"
        elif i == 1:
            label = "昨天"
        else:
            label = d.strftime("%m-%d")
            
        hourly_counts = [hourly_activity_by_day.get(date_str, {}).get(str(h).zfill(2), 0) for h in range(24)]
        days_data.append({
            "label": label,
            "date": date_str,
            "counts": hourly_counts
        })
        
    days_data_json = json.dumps(days_data)
    
    html = f"""
    <style>
        @keyframes activityFadeUp {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .activity-card {{
            position: relative;
            width: 100%;
            height: 260px;
            background:
                radial-gradient(circle at 88% 10%, rgba(0, 122, 255, 0.18), transparent 12rem),
                linear-gradient(180deg, #111722 0%, #0d1117 100%);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 10px;
            box-sizing: border-box;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.16);
            transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
            animation: activityFadeUp 0.4s ease both;
        }}
        .activity-card:hover {{
            transform: translateY(-2px);
            border-color: rgba(96, 165, 250, 0.34);
            box-shadow: 0 18px 44px rgba(15, 23, 42, 0.22);
        }}
        .activity-header {{
            position: absolute;
            top: 10px;
            left: 20px;
            right: 18px;
            z-index: 10;
            display: flex;
            align-items: center;
            gap: 14px;
            min-width: 0;
        }}
        .activity-title {{
            flex: 0 0 auto;
            color: #c9d1d9;
            font-size: 16px;
            font-weight: 700;
            white-space: nowrap;
        }}
        .day-selector-shell {{
            position: relative;
            flex: 1 1 auto;
            min-width: 160px;
            max-width: 460px;
            overflow-x: auto;
            overflow-y: hidden;
            background-color: rgba(255,255,255,0.055);
            padding: 3px;
            border-radius: 8px;
            scrollbar-width: thin;
            scrollbar-color: rgba(148, 163, 184, 0.45) transparent;
        }}
        .day-selector-shell::-webkit-scrollbar {{
            height: 5px;
        }}
        .day-selector-shell::-webkit-scrollbar-track {{
            background: transparent;
        }}
        .day-selector-shell::-webkit-scrollbar-thumb {{
            background: rgba(148, 163, 184, 0.45);
            border-radius: 999px;
        }}
        #day-selector {{
            position: relative;
            display: flex;
            gap: 6px;
            width: max-content;
            min-width: 100%;
        }}
        .day-selector-indicator {{
            position: absolute;
            top: 0;
            left: 0;
            height: 100%;
            width: 0;
            border-radius: 6px;
            background: linear-gradient(180deg, #2f3745 0%, #202733 100%);
            box-shadow: 0 6px 16px rgba(0,0,0,0.22), inset 0 1px 0 rgba(255,255,255,0.08);
            transform: translateX(0);
            transition: transform 0.24s cubic-bezier(.2,.8,.2,1), width 0.24s cubic-bezier(.2,.8,.2,1);
            z-index: 0;
            pointer-events: none;
        }}
        .day-selector-btn {{
            position: relative;
            z-index: 1;
            flex: 0 0 auto;
            padding: 3px 10px;
            min-width: 48px;
            border-radius: 6px;
            color: #8b949e;
            font-size: 12px;
            line-height: 18px;
            text-align: center;
            cursor: pointer;
            user-select: none;
            transition: color 0.18s ease, transform 0.18s ease;
        }}
        .day-selector-btn:hover {{
            color: #dbeafe;
        }}
        .day-selector-btn.active {{
            color: #ffffff;
            transform: translateY(-1px);
        }}
        #activity-chart {{
            width: 100%;
            height: 100%;
            transition: opacity 0.22s ease, transform 0.22s ease;
        }}
    </style>
    <div class="activity-card">
        <!-- 自定义图表头部与选项卡 -->
        <div class="activity-header">
            <div class="activity-title">
                ⏱️ 时段活动曲线 ⓘ
            </div>
            <div id="day-selector-shell" class="day-selector-shell" title="在这里滚动鼠标滚轮可左右切换日期条">
                <div id="day-selector">
                    <div id="day-selector-indicator" class="day-selector-indicator"></div>
                    <!-- 按钮由 JS 动态生成 -->
                </div>
            </div>
        </div>
        
        <div id="activity-chart"></div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
        var daysData = {days_data_json};
        var chartDom = document.getElementById('activity-chart');
        var myChart = echarts.init(chartDom);
        var currentDayIndex = 0;
        var hasRenderedActivityChart = false;
        var selectorShell = document.getElementById('day-selector-shell');
        var selector = document.getElementById('day-selector');
        var indicator = document.getElementById('day-selector-indicator');
        
        selectorShell.addEventListener('wheel', function(e) {{
            if (Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {{
                selectorShell.scrollLeft += e.deltaY;
                e.preventDefault();
            }}
        }}, {{ passive: false }});
        
        function moveDayIndicator(activeBtn) {{
            if (!activeBtn) return;
            indicator.style.width = activeBtn.offsetWidth + 'px';
            indicator.style.transform = 'translateX(' + activeBtn.offsetLeft + 'px)';
            var leftEdge = activeBtn.offsetLeft;
            var rightEdge = leftEdge + activeBtn.offsetWidth;
            if (leftEdge < selectorShell.scrollLeft) {{
                selectorShell.scrollTo({{ left: leftEdge - 8, behavior: 'smooth' }});
            }} else if (rightEdge > selectorShell.scrollLeft + selectorShell.clientWidth) {{
                selectorShell.scrollTo({{ left: rightEdge - selectorShell.clientWidth + 8, behavior: 'smooth' }});
            }}
        }}
        
        function refreshDayButtons(dayIndex) {{
            selector.querySelectorAll('.day-selector-btn').forEach(function(btn) {{
                var isActive = Number(btn.dataset.index) === dayIndex;
                btn.classList.toggle('active', isActive);
                if (isActive) {{
                    moveDayIndicator(btn);
                }}
            }});
        }}
        
        function buildDaySelector() {{
            daysData.forEach(function(day, index) {{
                var btn = document.createElement('div');
                btn.className = 'day-selector-btn';
                btn.dataset.index = index;
                btn.innerText = day.label;
                btn.onclick = function() {{
                    renderChart(index);
                }};
                selector.appendChild(btn);
            }});
            requestAnimationFrame(function() {{
                refreshDayButtons(currentDayIndex);
            }});
        }}
        
        function renderChart(dayIndex) {{
            currentDayIndex = dayIndex;
            var dayInfo = daysData[dayIndex];
            var hourly_counts = dayInfo.counts;
            var max_val = Math.max(...hourly_counts);
            if (max_val === 0) max_val = 1;
            
            if (hasRenderedActivityChart) {{
                chartDom.style.opacity = '0.72';
                chartDom.style.transform = 'translateX(14px)';
            }}
            
            var data = [];
            for (var i = 0; i <= 23; i++) {{
                var count = hourly_counts[i];
                var y = Math.sin((i - 6) / 24 * Math.PI * 2);
                data.push([i, y, count]);
            }}

            var option = {{
                backgroundColor: 'transparent',
                grid: {{ top: 40, bottom: 20, left: 20, right: 20, containLabel: true }},
                xAxis: {{
                    type: 'value',
                    min: 0, max: 23,
                    interval: 1,
                    axisLine: {{ show: false }},
                    splitLine: {{ show: false }},
                    axisTick: {{ show: false }},
                    axisLabel: {{
                        formatter: function (value) {{
                            if(value === 0) return '00:00';
                            if(value === 3) return '03:00';
                            if(value === 6) return '06:00';
                            if(value === 9) return '09:00';
                            if(value === 12) return '12:00';
                            if(value === 15) return '15:00';
                            if(value === 18) return '18:00';
                            if(value === 21) return '21:00';
                            if(value === 23) return '23:59';
                            return '';
                        }},
                        color: '#8b949e',
                        fontSize: 13,
                        fontFamily: 'monospace',
                        margin: 8
                    }}
                }},
                yAxis: {{
                    type: 'value',
                    min: -1.2, max: 1.5,
                    show: false
                }},
                series: [
                    {{
                        type: 'line',
                        data: data.map(function (item) {{ return [item[0], item[1]]; }}),
                        smooth: true,
                        symbol: 'none',
                        lineStyle: {{ color: '#444c56', width: 2 }},
                        z: 2, /* 明确线在下层 */
                        markLine: {{
                            symbol: ['none', 'none'],
                            label: {{ show: false }},
                            data: [
                                {{ yAxis: 0, lineStyle: {{ type: 'dashed', color: '#444c56', width: 1 }} }}
                            ]
                        }}
                    }},
                    {{
                        type: 'scatter',
                        data: data,
                        z: 4, /* 明确圆点在上层 */
                        symbolSize: function (data) {{
                            return 12 + (data[2] / max_val) * 16; 
                        }},
                        itemStyle: {{
                            color: function(params) {{
                                if (params.data[2] === 0) return 'rgba(255, 255, 255, 0.15)';
                                var opacity = 0.4 + (params.data[2] / max_val) * 0.6;
                                return 'rgba(255, 255, 255, ' + opacity + ')';
                            }}
                        }},
                        tooltip: {{
                            formatter: function(params) {{
                                var h = params.value[0];
                                var hStr1 = (h < 10 ? '0' + h : h) + ':00';
                                var hStr2 = (h < 10 ? '0' + h : h) + ':59';
                                return hStr1 + ' ~ ' + hStr2 + ' 录入/修改了 ' + params.value[2] + ' 次题目';
                            }}
                        }}
                    }},
                    // 太阳/月亮图标标记
                    {{
                        type: 'scatter',
                        data: [[6, 0, 0], [12, 1.2, 0], [18, 0, 0], [21, -0.7, 0]],
                        symbol: 'circle',
                        symbolSize: 0,
                        z: 3,
                        label: {{
                            show: true,
                            formatter: function(params) {{
                                if (params.data[0] === 6) return '🌅';
                                if (params.data[0] === 12) return '☀️';
                                if (params.data[0] === 18) return '🌇';
                                if (params.data[0] === 21) return '🌙';
                                return '';
                            }},
                            position: 'top',
                            distance: 14,
                            fontSize: 16
                        }}
                    }}
                ],
                tooltip: {{ 
                    trigger: 'item', 
                    backgroundColor: 'rgba(13, 17, 23, 0.9)', 
                    borderColor: '#30363d', 
                    textStyle: {{ color: '#c9d1d9' }},
                    formatter: function(params) {{
                        if (params.componentType === 'series' && params.seriesIndex === 1) {{
                            var h = params.value[0];
                            var hStr1 = (h < 10 ? '0' + h : h) + ':00';
                            var hStr2 = (h < 10 ? '0' + h : h) + ':59';
                            return hStr1 + ' ~ ' + hStr2 + ' 录入/修改了 ' + params.value[2] + ' 次题目';
                        }}
                    }}
                }}
            }};
            myChart.setOption(option, true);
            refreshDayButtons(dayIndex);
            requestAnimationFrame(function() {{
                chartDom.style.opacity = '1';
                chartDom.style.transform = 'translateX(0)';
            }});
            hasRenderedActivityChart = true;
        }}
        
        // 初始渲染今天
        buildDaySelector();
        renderChart(0);
        window.addEventListener('resize', function() {{
            myChart.resize();
            refreshDayButtons(currentDayIndex);
        }});
    </script>
    """
    return html

def generate_activity_curve_html(hourly_activity_by_day):
    today = datetime.date.today()
    days_data = []
    for i in range(6, -1, -1):
        d = today - datetime.timedelta(days=i)
        date_str = d.isoformat()
        if i == 0:
            label = "今天"
        elif i == 1:
            label = "昨天"
        else:
            label = d.strftime("%m-%d")

        hourly_counts = [hourly_activity_by_day.get(date_str, {}).get(str(h).zfill(2), 0) for h in range(24)]
        days_data.append({
            "label": label,
            "date": date_str,
            "counts": hourly_counts
        })

    timeline = []
    for day_index, day in enumerate(days_data):
        for hour, count in enumerate(day["counts"]):
            timeline.append({
                "dayIndex": day_index,
                "dayLabel": day["label"],
                "date": day["date"],
                "hour": hour,
                "count": count
            })

    days_data_json = json.dumps(days_data)
    timeline_json = json.dumps(timeline)
    default_start = max(0, len(timeline) - 24)
    default_end = max(23, len(timeline) - 1)

    html = f"""
    <style>
        @keyframes activityFadeUp {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .activity-card {{
            position: relative;
            width: 100%;
            height: 300px;
            background:
                radial-gradient(circle at 88% 10%, rgba(0, 122, 255, 0.10), transparent 12rem),
                linear-gradient(180deg, rgba(249, 250, 255, 0.96) 0%, rgba(235, 241, 251, 0.94) 100%);
            border-radius: 12px;
            border: 1px solid rgba(96, 125, 170, 0.18);
            padding: 10px;
            box-sizing: border-box;
            box-shadow: 0 14px 34px rgba(31, 35, 48, 0.08);
            transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
            animation: activityFadeUp 0.4s ease both;
        }}
        .activity-card:hover {{
            transform: translateY(-2px);
            border-color: rgba(96, 125, 170, 0.28);
            box-shadow: 0 18px 44px rgba(31, 35, 48, 0.12);
        }}
        .activity-header {{
            position: absolute;
            top: 10px;
            left: 20px;
            right: 18px;
            z-index: 10;
            display: flex;
            align-items: center;
            gap: 14px;
            min-width: 0;
        }}
        .activity-title {{
            flex: 0 0 auto;
            color: #263241;
            font-size: 16px;
            font-weight: 700;
            white-space: nowrap;
            padding-right: 2px;
        }}
        .day-selector-shell {{
            position: relative;
            flex: 0 1 560px;
            min-width: 430px;
            max-width: 560px;
            overflow: hidden;
            background:
                linear-gradient(180deg, rgba(255,255,255,0.92), rgba(241,245,249,0.78));
            padding: 4px;
            border-radius: 999px;
            border: 1px solid rgba(96, 125, 170, 0.16);
            box-shadow: inset 0 1px 1px rgba(255,255,255,0.72);
        }}
        #day-selector {{
            position: relative;
            display: flex;
            gap: 3px;
            min-width: 100%;
        }}
        .day-selector-indicator {{
            position: absolute;
            top: 0;
            left: 0;
            height: 100%;
            width: 0;
            border-radius: 999px;
            background: linear-gradient(180deg, rgba(59, 130, 246, 0.94), rgba(37, 99, 235, 0.78));
            box-shadow: 0 8px 20px rgba(37, 99, 235, 0.20), inset 0 1px 0 rgba(255,255,255,0.28);
            transform: translateX(0);
            transition: transform 0.24s cubic-bezier(.2,.8,.2,1), width 0.24s cubic-bezier(.2,.8,.2,1);
            z-index: 0;
            pointer-events: none;
        }}
        .day-selector-btn {{
            position: relative;
            z-index: 1;
            flex: 1 1 0;
            padding: 4px 10px;
            min-width: 54px;
            border-radius: 999px;
            color: #64748b;
            font-size: 12px;
            line-height: 18px;
            text-align: center;
            cursor: pointer;
            user-select: none;
            transition: color 0.18s ease, transform 0.18s ease;
        }}
        .day-selector-btn:hover {{
            color: #1d4ed8;
        }}
        .day-selector-btn.active {{
            color: #ffffff;
            transform: translateY(-0.5px);
            text-shadow: 0 1px 8px rgba(219, 234, 254, 0.32);
        }}
        .day-selector-btn.today {{
            min-width: 62px;
            font-weight: 700;
        }}
        @media (max-width: 760px) {{
            .activity-header {{
                align-items: flex-start;
                flex-direction: column;
                gap: 8px;
            }}
            .day-selector-shell {{
                flex-basis: auto;
                width: calc(100% - 2px);
                min-width: 0;
                max-width: none;
            }}
        }}
        #activity-chart {{
            width: 100%;
            height: 100%;
            transition: opacity 0.22s ease, transform 0.22s ease;
        }}
    </style>
    <div class="activity-card">
        <div class="activity-header">
            <div class="activity-title">⏱️ 时段活动曲线 ⓘ</div>
            <div class="day-selector-shell" title="点击日期可快速跳转，拖动下方时间滚条可连续查看">
                <div id="day-selector">
                    <div id="day-selector-indicator" class="day-selector-indicator"></div>
                </div>
            </div>
        </div>
        <div id="activity-chart"></div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
        var daysData = {days_data_json};
        var timelineData = {timeline_json};
        var defaultStart = {default_start};
        var defaultEnd = {default_end};
        var chartDom = document.getElementById('activity-chart');
        var myChart = echarts.init(chartDom, 'dark');
        var currentDayIndex = daysData.length - 1;
        var hasRenderedActivityChart = false;
        var selector = document.getElementById('day-selector');
        var indicator = document.getElementById('day-selector-indicator');

        function moveDayIndicator(activeBtn) {{
            if (!activeBtn) return;
            indicator.style.width = activeBtn.offsetWidth + 'px';
            indicator.style.transform = 'translateX(' + activeBtn.offsetLeft + 'px)';
        }}

        function refreshDayButtons(dayIndex) {{
            selector.querySelectorAll('.day-selector-btn').forEach(function(btn) {{
                var isActive = Number(btn.dataset.index) === dayIndex;
                btn.classList.toggle('active', isActive);
                if (isActive) moveDayIndicator(btn);
            }});
        }}

        function buildDaySelector() {{
            daysData.forEach(function(day, index) {{
                var btn = document.createElement('div');
                btn.className = 'day-selector-btn';
                if (index === daysData.length - 1) btn.classList.add('today');
                btn.dataset.index = index;
                btn.innerText = day.label;
                btn.onclick = function() {{ jumpToDay(index); }};
                selector.appendChild(btn);
            }});
            requestAnimationFrame(function() {{ refreshDayButtons(currentDayIndex); }});
        }}

        function getVisibleDayIndexFromRange(startValue, endValue) {{
            var center = Math.round((Number(startValue) + Number(endValue)) / 2);
            center = Math.max(0, Math.min(timelineData.length - 1, center));
            return timelineData[center].dayIndex;
        }}

        function getZoomRange(dataZoomOption) {{
            var startValue = Number(dataZoomOption.startValue);
            var endValue = Number(dataZoomOption.endValue);
            if (Number.isFinite(startValue) && Number.isFinite(endValue)) {{
                return [startValue, endValue];
            }}
            var maxIndex = Math.max(0, timelineData.length - 1);
            var startPercent = Number.isFinite(Number(dataZoomOption.start)) ? Number(dataZoomOption.start) : 0;
            var endPercent = Number.isFinite(Number(dataZoomOption.end)) ? Number(dataZoomOption.end) : 100;
            return [
                Math.round(maxIndex * startPercent / 100),
                Math.round(maxIndex * endPercent / 100)
            ];
        }}

        function getVisibleSpan() {{
            var opt = myChart.getOption();
            if (!opt || !opt.dataZoom || !opt.dataZoom[0]) {{
                return defaultEnd - defaultStart + 1;
            }}
            var range = getZoomRange(opt.dataZoom[0]);
            return Math.max(1, range[1] - range[0] + 1);
        }}

        function getTimeLabelStep(visibleSpan) {{
            if (visibleSpan <= 18) return 1;
            if (visibleSpan <= 30) return 2;
            if (visibleSpan <= 48) return 3;
            if (visibleSpan <= 84) return 6;
            return 12;
        }}

        function jumpToDay(dayIndex) {{
            currentDayIndex = dayIndex;
            refreshDayButtons(dayIndex);
            var startValue = dayIndex * 24;
            var endValue = Math.min(startValue + 23, timelineData.length - 1);
            myChart.dispatchAction({{
                type: 'dataZoom',
                startValue: startValue,
                endValue: endValue
            }});
        }}

        function renderChart() {{
            var maxVal = Math.max.apply(null, timelineData.map(function(item) {{ return item.count; }}));
            if (maxVal === 0) maxVal = 1;

            if (hasRenderedActivityChart) {{
                chartDom.style.opacity = '0.72';
                chartDom.style.transform = 'translateX(10px)';
            }}

            var lineData = timelineData.map(function(item, index) {{
                var y = Math.sin((item.hour - 6) / 24 * Math.PI * 2);
                return [index, y, item.count, item.dayLabel, item.date, item.hour];
            }});

            var iconData = [];
            var dayBoundaryData = [];
            timelineData.forEach(function(item, index) {{
                if (item.hour === 0) {{
                    dayBoundaryData.push({{
                        xAxis: index,
                        label: {{
                            show: true,
                            formatter: item.dayLabel,
                            position: 'insideStartTop',
                            distance: 18,
                            color: '#2563eb',
                            fontSize: 12,
                            fontWeight: 700,
                            backgroundColor: 'rgba(219, 234, 254, 0.88)',
                            borderRadius: 4,
                            padding: [2, 6]
                        }},
                        lineStyle: {{
                            color: 'rgba(37, 99, 235, 0.22)',
                            type: 'dashed',
                            width: 1
                        }}
                    }});
                }}
                if (item.hour === 6) iconData.push([index, 0, 0, item.dayLabel, item.date, item.hour, '🌅']);
                if (item.hour === 12) iconData.push([index, 1.2, 0, item.dayLabel, item.date, item.hour, '☀️']);
                if (item.hour === 18) iconData.push([index, 0, 0, item.dayLabel, item.date, item.hour, '🌆']);
                if (item.hour === 21) iconData.push([index, -0.7, 0, item.dayLabel, item.date, item.hour, '🌙']);
            }});

            var option = {{
                backgroundColor: 'transparent',
                animationDurationUpdate: 280,
                animationEasingUpdate: 'cubicOut',
                grid: {{ top: 50, bottom: 54, left: 20, right: 20, containLabel: true }},
                xAxis: {{
                    type: 'value',
                    min: 0,
                    max: timelineData.length - 1,
                    axisLine: {{ show: false }},
                    splitLine: {{ show: false }},
                    axisTick: {{ show: false }},
                    axisLabel: {{
                        formatter: function(value) {{
                            var idx = Math.round(value);
                            var item = timelineData[idx];
                            if (!item) return '';
                            if (Math.abs(value - idx) > 0.12) return '';
                            var step = getTimeLabelStep(getVisibleSpan());
                            if (idx % step !== 0) return '';
                            if (item.hour === 0 && step > 3) return '';
                            return (item.hour < 10 ? '0' + item.hour : item.hour) + ':00';
                        }},
                        hideOverlap: true,
                        showMinLabel: false,
                        showMaxLabel: false,
                        color: '#64748b',
                        fontSize: 12,
                        fontFamily: 'monospace',
                        margin: 8
                    }}
                }},
                yAxis: {{
                    type: 'value',
                    min: -1.2,
                    max: 1.5,
                    show: false
                }},
                dataZoom: [
                    {{
                        type: 'inside',
                        xAxisIndex: 0,
                        filterMode: 'none',
                        zoomOnMouseWheel: false,
                        moveOnMouseWheel: true,
                        moveOnMouseMove: true,
                        preventDefaultMouseMove: true,
                        startValue: defaultStart,
                        endValue: defaultEnd
                    }},
                    {{
                        type: 'slider',
                        xAxisIndex: 0,
                        filterMode: 'none',
                        height: 18,
                        bottom: 8,
                        startValue: defaultStart,
                        endValue: defaultEnd,
                        borderColor: 'rgba(96, 125, 170, 0.22)',
                        backgroundColor: 'rgba(148, 163, 184, 0.14)',
                        fillerColor: 'rgba(59, 130, 246, 0.22)',
                        dataBackground: {{
                            lineStyle: {{ color: 'rgba(100, 116, 139, 0.30)' }},
                            areaStyle: {{ color: 'rgba(148, 163, 184, 0.12)' }}
                        }},
                        selectedDataBackground: {{
                            lineStyle: {{ color: 'rgba(37, 99, 235, 0.55)' }},
                            areaStyle: {{ color: 'rgba(59, 130, 246, 0.18)' }}
                        }},
                        handleSize: '110%',
                        handleStyle: {{
                            color: '#2563eb',
                            borderColor: 'rgba(37, 99, 235, 0.72)',
                            shadowBlur: 8,
                            shadowColor: 'rgba(37, 99, 235, 0.24)'
                        }},
                        moveHandleSize: 6,
                        textStyle: {{ color: '#64748b', fontSize: 10 }}
                    }}
                ],
                series: [
                    {{
                        type: 'line',
                        data: lineData.map(function(item) {{ return [item[0], item[1]]; }}),
                        smooth: true,
                        symbol: 'none',
                        lineStyle: {{ color: 'rgba(71, 85, 105, 0.44)', width: 2 }},
                        z: 2,
                        markLine: {{
                            symbol: ['none', 'none'],
                            label: {{ show: false }},
                            data: [
                                {{ yAxis: 0, lineStyle: {{ type: 'dashed', color: 'rgba(71, 85, 105, 0.32)', width: 1 }} }}
                            ].concat(dayBoundaryData)
                        }}
                    }},
                    {{
                        type: 'scatter',
                        data: lineData,
                        z: 4,
                        symbolSize: function(data) {{
                            return 12 + (data[2] / maxVal) * 16;
                        }},
                        itemStyle: {{
                            color: function(params) {{
                                if (params.data[2] === 0) return 'rgba(71, 85, 105, 0.22)';
                                var opacity = 0.4 + (params.data[2] / maxVal) * 0.6;
                                return 'rgba(37, 99, 235, ' + opacity + ')';
                            }}
                        }}
                    }},
                    {{
                        type: 'scatter',
                        data: iconData,
                        symbol: 'circle',
                        symbolSize: 0,
                        z: 3,
                        label: {{
                            show: true,
                            formatter: function(params) {{ return params.data[6] || ''; }},
                            position: 'top',
                            distance: 14,
                            fontSize: 16
                        }}
                    }}
                ],
                tooltip: {{
                    trigger: 'item',
                    backgroundColor: 'rgba(255, 255, 255, 0.94)',
                    borderColor: 'rgba(96, 125, 170, 0.22)',
                    textStyle: {{ color: '#263241' }},
                    formatter: function(params) {{
                        if (params.componentType === 'series' && params.seriesIndex === 1) {{
                            var h = params.value[5];
                            var hStr1 = (h < 10 ? '0' + h : h) + ':00';
                            var hStr2 = (h < 10 ? '0' + h : h) + ':59';
                            return params.value[3] + ' ' + hStr1 + ' ~ ' + hStr2 + '<br/>录入/修改了 ' + params.value[2] + ' 次题目';
                        }}
                        return '';
                    }}
                }}
            }};

            myChart.setOption(option, true);
            requestAnimationFrame(function() {{
                chartDom.style.opacity = '1';
                chartDom.style.transform = 'translateX(0)';
            }});
            hasRenderedActivityChart = true;
        }}

        myChart.on('dataZoom', function() {{
            var dz = myChart.getOption().dataZoom[0];
            if (!dz) return;
            var range = getZoomRange(dz);
            var dayIndex = getVisibleDayIndexFromRange(range[0], range[1]);
            if (dayIndex !== currentDayIndex) {{
                currentDayIndex = dayIndex;
                refreshDayButtons(dayIndex);
            }}
            myChart.setOption({{ xAxis: {{ axisLabel: {{}} }} }});
        }});

        buildDaySelector();
        renderChart();
        refreshDayButtons(currentDayIndex);
        window.addEventListener('resize', function() {{
            myChart.resize();
            refreshDayButtons(currentDayIndex);
        }});
    </script>
    """
    return html

def generate_echarts_bar_html(data_dict, title):
    if not data_dict:
        return "<div style='color: gray;'>暂无数据</div>"
    
    # 排序
    sorted_items = sorted(data_dict.items(), key=lambda x: x[1], reverse=True)
    labels = [x[0] for x in sorted_items]
    values = [x[1] for x in sorted_items]
    
    html = f"""
    <style>
        @keyframes chartPanelFadeUp {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .echarts-panel {{
            width: 100%;
            height: 350px;
            padding: 10px 12px 6px;
            box-sizing: border-box;
            border-radius: 12px;
            border: 1px solid rgba(109, 40, 217, 0.10);
            background:
                linear-gradient(180deg, rgba(255,255,255,0.90), rgba(255,255,255,0.72)),
                rgba(255,255,255,0.82);
            box-shadow: 0 10px 30px rgba(31, 35, 48, 0.06);
            transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
            animation: chartPanelFadeUp 0.4s ease both;
        }}
        .echarts-panel:hover {{
            transform: translateY(-2px);
            border-color: rgba(109, 40, 217, 0.18);
            box-shadow: 0 16px 40px rgba(31, 35, 48, 0.10);
        }}
        #bar-chart {{
            width: 100%;
            height: 100%;
        }}
    </style>
    <div class="echarts-panel"><div id="bar-chart"></div></div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
        var chartDom = document.getElementById('bar-chart');
        var myChart = echarts.init(chartDom);
        var option = {{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
            animationDuration: 800,
            animationEasing: 'cubicOut',
            grid: {{ left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true }},
            xAxis: {{
                type: 'category',
                data: {json.dumps(labels)},
                axisLabel: {{ interval: 0, rotate: 30, color: '#31333F', fontWeight: 'bold' }},
                axisLine: {{ lineStyle: {{ color: '#ccc' }} }}
            }},
            yAxis: {{
                type: 'value',
                splitLine: {{ lineStyle: {{ color: '#eee', type: 'dashed' }} }},
                axisLabel: {{ color: '#31333F', fontWeight: 'bold' }}
            }},
            series: [{{
                data: {json.dumps(values)},
                type: 'bar',
                barWidth: '40%',
                itemStyle: {{
                    borderRadius: [6, 6, 0, 0],
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        {{ offset: 0, color: '#8b5cf6' }},
                        {{ offset: 1, color: '#4c1d95' }}
                    ])
                }}
            }}]
        }};
        myChart.setOption(option);
        window.addEventListener('resize', function() {{ myChart.resize(); }});
    </script>
    """
    return html

def generate_echarts_pie_html(data_dict, diff_dict, title):
    if not data_dict and not diff_dict:
        return "<div style='color: gray;'>暂无数据</div>"
    
    # 内圈：题型占比
    pie_data_inner = []
    if data_dict:
        for k, v in data_dict.items():
            if isinstance(k, dict): k = str(k)
            pie_data_inner.append({"name": k, "value": v})
            
    # 外圈：难度分布
    pie_data_outer = []
    if diff_dict:
        for k, v in diff_dict.items():
            if isinstance(k, dict): k = str(k)
            pie_data_outer.append({"name": k, "value": v})
    
    html = f"""
    <style>
        @keyframes piePanelFadeUp {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .pie-panel {{
            width: 100%;
            height: 350px;
            padding: 10px 12px 6px;
            box-sizing: border-box;
            border-radius: 12px;
            border: 1px solid rgba(109, 40, 217, 0.10);
            background:
                linear-gradient(180deg, rgba(255,255,255,0.90), rgba(255,255,255,0.72)),
                rgba(255,255,255,0.82);
            box-shadow: 0 10px 30px rgba(31, 35, 48, 0.06);
            transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
            animation: piePanelFadeUp 0.4s ease both;
        }}
        .pie-panel:hover {{
            transform: translateY(-2px);
            border-color: rgba(109, 40, 217, 0.18);
            box-shadow: 0 16px 40px rgba(31, 35, 48, 0.10);
        }}
        #pie-chart {{
            width: 100%;
            height: 100%;
        }}
    </style>
    <div class="pie-panel"><div id="pie-chart"></div></div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
        var chartDom = document.getElementById('pie-chart');
        var myChart = echarts.init(chartDom);
        var option = {{
            animationDuration: 850,
            animationEasing: 'cubicOut',
            tooltip: {{ trigger: 'item', formatter: '{{a}} <br/>{{b}}: {{c}} ({{d}}%)' }},
            legend: [
                {{ top: '0%', left: 'center', textStyle: {{ color: '#31333F', fontWeight: 'bold' }}, data: {json.dumps([item['name'] for item in pie_data_inner])} }},
                {{ top: '6%', left: 'center', textStyle: {{ color: '#31333F', fontWeight: 'bold' }}, data: {json.dumps([item['name'] for item in pie_data_outer])} }}
            ],
            color: ['#8b5cf6', '#3b82f6', '#ec4899', '#10b981', '#f59e0b', '#f97316', '#ef4444', '#14b8a6', '#8b5cf6'],
            series: [
                {{
                    name: '题型分布',
                    type: 'pie',
                    selectedMode: 'single',
                    radius: [0, '40%'],
                    center: ['50%', '58%'],
                    label: {{ position: 'inner', fontSize: 13, fontWeight: 'bold', color: '#fff' }},
                    labelLine: {{ show: false }},
                    data: {json.dumps(pie_data_inner)}
                }},
                {{
                    name: '难度星级分布',
                    type: 'pie',
                    radius: ['55%', '75%'],
                    center: ['50%', '58%'],
                    itemStyle: {{ borderRadius: 4, borderColor: '#ffffff', borderWidth: 2 }},
                    label: {{
                        formatter: '{{b|{{b}}}}\\n{{c|{{c}}道}}',
                        rich: {{
                            b: {{ color: '#31333F', fontSize: 13, fontWeight: 'bold', lineHeight: 20 }},
                            c: {{ color: '#555555', fontSize: 12, fontWeight: 'bold' }}
                        }}
                    }},
                    data: {json.dumps(pie_data_outer)}
                }}
            ]
        }};
        myChart.setOption(option);
        window.addEventListener('resize', function() {{ myChart.resize(); }});
    </script>
    """
    return html
