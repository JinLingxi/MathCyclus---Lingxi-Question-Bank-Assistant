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
        background-color: #0d1117;
        color: #c9d1d9;
        padding: 20px;
        border-radius: 10px;
        width: 100%;
        height: 270px;
        box-sizing: border-box;
        overflow: hidden;
        margin-bottom: 0px;
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
        background: #0d1117;
        border-radius: 4px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-thumb {{
        background: #444c56; /* 灰色滚动条 */
        border-radius: 4px;
    }}
    .heatmap-scroll-area::-webkit-scrollbar-thumb:hover {{
        background: #768390;
    }}
    .heatmap-title {{
        font-size: 18px;
        font-weight: 600;
        margin-bottom: -10px; /* 减小标题自带的底部边距，依靠 scroll-area 的 padding-top 撑开 */
        color: #c9d1d9;
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
        background-color: #2d333b;
        position: relative;
    }}
    .heatmap-cell[data-level="1"] {{ background-color: #0e4429; }}
    .heatmap-cell[data-level="2"] {{ background-color: #006d32; }}
    .heatmap-cell[data-level="3"] {{ background-color: #26a641; }}
    .heatmap-cell[data-level="4"] {{ background-color: #39d353; }}
    .heatmap-cell.hidden {{ background-color: transparent; pointer-events: none; }}
    
    .heatmap-footer {{
        display: flex;
        justify-content: flex-end;
        width: 100%;
        margin-top: 10px;
        font-size: 14px;
        color: #8b949e;
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
            <div style="display: flex; flex-direction: column; gap: 4px; font-size: 14px; color: #8b949e; margin-right: 8px; margin-top: 20px; position: sticky; left: 0; background-color: #0d1117; z-index: 2;">
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
                <div class="legend-cell" style="background-color: #2d333b;"></div>
                <div class="legend-cell" style="background-color: #0e4429;"></div>
                <div class="legend-cell" style="background-color: #006d32;"></div>
                <div class="legend-cell" style="background-color: #26a641;"></div>
                <div class="legend-cell" style="background-color: #39d353;"></div>
                More
            </div>
        </div>
    </div>
    """
    return html

def generate_activity_curve_html(hourly_activity_by_day):
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
    <div style="position: relative; width: 100%; height: 260px; background-color: #0d1117; border-radius: 10px; padding: 10px; box-sizing: border-box;">
        <!-- 自定义图表头部与选项卡 -->
        <div style="position: absolute; top: 10px; left: 20px; z-index: 10; display: flex; align-items: center; gap: 15px;">
            <div style="color: #c9d1d9; font-size: 16px; font-weight: bold;">
                ⏱️ 时段活动曲线 ⓘ
            </div>
            <div id="day-selector" style="display: flex; gap: 6px; background-color: rgba(255,255,255,0.05); padding: 3px; border-radius: 6px;">
                <!-- 按钮由 JS 动态生成 -->
            </div>
        </div>
        
        <div id="activity-chart" style="width: 100%; height: 100%;"></div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
        var daysData = {days_data_json};
        var chartDom = document.getElementById('activity-chart');
        var myChart = echarts.init(chartDom, 'dark');
        
        function renderChart(dayIndex) {{
            var dayInfo = daysData[dayIndex];
            var hourly_counts = dayInfo.counts;
            var max_val = Math.max(...hourly_counts);
            if (max_val === 0) max_val = 1;
            
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
            myChart.setOption(option);
            
            // 更新选项卡 UI
            var selector = document.getElementById('day-selector');
            selector.innerHTML = '';
            daysData.forEach(function(day, index) {{
                var btn = document.createElement('div');
                btn.innerText = day.label;
                btn.style.padding = '2px 8px';
                btn.style.fontSize = '12px';
                btn.style.borderRadius = '4px';
                btn.style.cursor = 'pointer';
                btn.style.color = index === dayIndex ? '#ffffff' : '#8b949e';
                btn.style.backgroundColor = index === dayIndex ? '#21262d' : 'transparent';
                btn.style.transition = 'all 0.2s';
                
                btn.onmouseover = function() {{
                    if (index !== dayIndex) btn.style.backgroundColor = 'rgba(255,255,255,0.1)';
                }};
                btn.onmouseout = function() {{
                    if (index !== dayIndex) btn.style.backgroundColor = 'transparent';
                }};
                
                btn.onclick = function() {{
                    renderChart(index);
                }};
                selector.appendChild(btn);
            }});
        }}
        
        // 初始渲染今天
        renderChart(0);
        window.addEventListener('resize', function() {{ myChart.resize(); }});
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
    <div id="bar-chart" style="width: 100%; height: 350px;"></div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
        var chartDom = document.getElementById('bar-chart');
        var myChart = echarts.init(chartDom);
        var option = {{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
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
    <div id="pie-chart" style="width: 100%; height: 350px;"></div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script>
        var chartDom = document.getElementById('pie-chart');
        var myChart = echarts.init(chartDom);
        var option = {{
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