// Chart Management Module
class ChartManager {
    constructor() {
        this.monthlyChart = null;
        this.dailyChart = null;
        this.setupChartDefaults();
    }

    // Setup Chart.js default animations
    setupChartDefaults() {
        Chart.defaults.datasets.bar.animation = {
            duration: 1200,
            easing: 'easeInOutQuart',
            delay: (ctx) => ctx.dataIndex * 80
        };

        Chart.defaults.datasets.line.animation = {
            duration: 1200,
            easing: 'easeInOutQuart',
            delay: (ctx) => ctx.dataIndex * 30
        };
    }    // Tạo biểu đồ tháng (bao gồm kỳ hiện tại)
    createMonthlyChart(monthlyData, currentPeriod, onClickCallback) {
        if (this.monthlyChart) {
            this.monthlyChart.destroy();
        }

        // Chuẩn bị dữ liệu biểu đồ
        const labels = [];
        const consumptionData = [];
        const costData = [];
        const backgroundColors = [];
        const borderColors = [];

        // Thêm dữ liệu từ monthlyData
        monthlyData.SanLuong.forEach((item, index) => {
            labels.push(`Tháng ${item.Tháng}/${item.Năm.toString().slice(-2)}`);
            consumptionData.push(parseInt(item["Điện tiêu thụ (KWh)"] || 0));

            // Tìm dữ liệu tiền điện tương ứng
            const correspondingCost = monthlyData.TienDien.find(cost => cost.Tháng === item.Tháng && cost.Năm === item.Năm);
            costData.push(parseInt(correspondingCost ? correspondingCost["Tiền Điện"] : 0));

            backgroundColors.push('rgba(147, 112, 219, 0.8)');
            borderColors.push('rgba(147, 112, 219, 1)');
        });        // Thêm dữ liệu kỳ hiện tại nếu có
        if (currentPeriod) {
            labels.push('Kỳ này');
            consumptionData.push(currentPeriod.consumption);
            costData.push(currentPeriod.cost);
            backgroundColors.push('rgba(255, 193, 7, 0.8)'); // Màu vàng cho kỳ hiện tại
            borderColors.push('rgba(255, 193, 7, 1)');
        }

        const ctx = document.getElementById('monthlyChart');
        this.monthlyChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Tiêu thụ (kWh)',
                        data: consumptionData,
                        backgroundColor: backgroundColors,
                        borderColor: borderColors,
                        borderWidth: 1,
                        yAxisID: 'y1',
                        datalabels: { display: false }
                    },
                    {
                        label: 'Hóa đơn (VND)',
                        data: costData,
                        backgroundColor: costData.map((_, index) =>
                            index === costData.length - 1 && currentPeriod ?
                                'rgba(255, 152, 0, 0.8)' : 'rgba(233, 97, 171, 0.8)'
                        ),
                        borderColor: costData.map((_, index) =>
                            index === costData.length - 1 && currentPeriod ?
                                'rgba(255, 152, 0, 1)' : 'rgba(233, 97, 171, 1)'
                        ),
                        borderWidth: 1,
                        yAxisID: 'y2',
                        datalabels: { display: false }
                    }
                ]
            }, options: {
                animation: {
                    duration: 800, // Giảm thời gian animation
                    easing: 'easeOutQuart'
                },
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                hover: {
                    animationDuration: 0 // Tắt animation khi hover
                },
                scales: {
                    y1: {
                        type: 'linear',
                        position: 'left',
                        beginAtZero: true,
                        ticks: {
                            color: this.getCurrentThemeColors().textColor
                        },
                        title: {
                            display: true,
                            text: 'Tiêu thụ (kWh)',
                            color: this.getCurrentThemeColors().textColor
                        }
                    }, y2: {
                        type: 'linear',
                        position: 'right',
                        beginAtZero: true,
                        ticks: {
                            color: this.getCurrentThemeColors().textColor
                        },
                        title: {
                            display: true,
                            text: 'Hóa đơn (VND)',
                            color: this.getCurrentThemeColors().textColor
                        },
                        grid: { drawOnChartArea: false }
                    }
                }, plugins: {
                    legend: {
                        labels: {
                            color: this.getCurrentThemeColors().textColor
                        }
                    },
                    tooltip: {
                        animation: {
                            duration: 0 // Tắt animation tooltip để tránh nháy
                        }, callbacks: {
                            label: function (context) {
                                const isCurrentPeriod = context.label === 'Kỳ này';

                                if (context.datasetIndex === 0) {
                                    // Dataset tiêu thụ
                                    let label = `${context.dataset.label}: ${context.parsed.y.toFixed(2)} kWh`;
                                    if (isCurrentPeriod && currentPeriod) {
                                        label += `\n📅 Kỳ: ${currentPeriod.period.start.toLocaleDateString('vi-VN')} → ${currentPeriod.period.end.toLocaleDateString('vi-VN')}`;
                                        label += `\n📊 Đã có ${currentPeriod.days} ngày dữ liệu`;
                                    }
                                    return label;
                                } else {
                                    // Dataset hóa đơn
                                    let label = `${context.dataset.label}: ${context.parsed.y.toLocaleString()} VND`;
                                    if (isCurrentPeriod) {
                                        label += ` (tạm tính)`;
                                        if (currentPeriod && currentPeriod.details) {
                                            label += `\n💡 Trước thuế: ${currentPeriod.details.subtotal.toLocaleString()} VND`;
                                            label += `\n🏛️ Thuế 8%: ${currentPeriod.details.tax.toLocaleString()} VND`;
                                        }
                                    }
                                    return label;
                                }
                            }
                        }
                    }
                },
                maintainAspectRatio: false,
                responsive: true,
                onClick: onClickCallback
            }
        });

        return this.monthlyChart;
    }

    // Tạo biểu đồ ngày
    createDailyChart(filteredData) {
        const data = filteredData.filter(day => day["Điện tiêu thụ (kWh)"] > 0);
        data.sort((a, b) =>
            new Date(a.Ngày.split('-').reverse().join('-')) -
            new Date(b.Ngày.split('-').reverse().join('-'))
        );

        // Tính trend cho mỗi ngày
        data.forEach((day, idx, arr) => {
            if (idx === 0) {
                day._trend = 'flat';
                day._trendValue = 0;
            } else {
                const prev = arr[idx - 1]["Điện tiêu thụ (kWh)"];
                const val = day["Điện tiêu thụ (kWh)"];
                day._trend = val > prev ? 'up' : (val < prev ? 'down' : 'flat');
                day._trendValue = val - prev;
            }
        });

        const dailyLabels = data.map(day => day.Ngày);
        const dailyDataValues = data.map(day => day["Điện tiêu thụ (kWh)"]);

        // Highlight max/min
        const maxVal = Math.max(...dailyDataValues);
        const minVal = Math.min(...dailyDataValues);

        const pointBackgroundColors = dailyDataValues.map(v =>
            v === maxVal ? '#2ecc40' : v === minVal ? '#e74c3c' : 'rgba(233,97,171,0.6)'
        );
        const pointRadius = dailyDataValues.map(v =>
            v === maxVal || v === minVal ? 7 : 4
        );
        const pointStyle = dailyDataValues.map(v =>
            v === maxVal ? 'star' : v === minVal ? 'triangle' : 'circle'
        );

        if (this.dailyChart) {
            this.dailyChart.destroy();
        }

        const ctx = document.getElementById('dailyChart');
        this.dailyChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dailyLabels,
                datasets: [{
                    label: 'Tiêu thụ (kWh)',
                    data: dailyDataValues,
                    fill: true,
                    backgroundColor: 'rgba(233, 97, 171, 0.2)',
                    borderColor: data.map((day, idx) => {
                        if (idx === 0) return 'rgba(147, 112, 219, 1)';
                        if (day._trend === 'up') return 'rgba(46, 204, 113, 1)';
                        if (day._trend === 'down') return 'rgba(231, 76, 60, 1)';
                        return 'rgba(147, 112, 219, 1)';
                    }),
                    segment: {
                        borderColor: ctx => {
                            const v = dailyDataValues[ctx.p0DataIndex];
                            if (v === maxVal) return '#2ecc40';
                            if (v === minVal) return '#e74c3c';
                            return data[ctx.p0DataIndex]._trend === 'up' ?
                                'rgba(46,204,113,1)' :
                                data[ctx.p0DataIndex]._trend === 'down' ?
                                    'rgba(231,76,60,1)' : 'rgba(147,112,219,1)';
                        }
                    }, tension: 0.4,
                    pointBackgroundColor: pointBackgroundColors,
                    pointRadius: pointRadius,
                    pointStyle: pointStyle,
                    pointHoverRadius: 8, // Giảm kích thước hover
                    pointHoverBackgroundColor: '#e961ab',
                    pointBorderWidth: 1, // Giảm border width
                }]
            }, options: {
                animation: {
                    duration: 800, // Giảm thời gian animation
                    easing: 'easeOutQuart'
                },
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                hover: {
                    animationDuration: 0 // Tắt animation khi hover
                }, scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            color: this.getCurrentThemeColors().textColor
                        }
                    }
                }, plugins: {
                    legend: {
                        labels: {
                            color: this.getCurrentThemeColors().textColor
                        }
                    },
                    tooltip: {
                        animation: {
                            duration: 0 // Tắt animation tooltip để tránh nháy
                        },
                        callbacks: {
                            label: function (context) {
                                const idx = context.dataIndex;
                                const day = data[idx];
                                let label = `${context.dataset.label}: ${context.parsed.y.toFixed(2)} kWh`;

                                if (typeof day._trend !== 'undefined' && idx > 0) {
                                    const trendText = day._trend === 'up' ? '↗️' :
                                        day._trend === 'down' ? '↘️' : '➡️';
                                    label += ` ${trendText} ${day._trendValue > 0 ? '+' : ''}${day._trendValue.toFixed(2)}`;
                                }

                                if (context.parsed.y === maxVal) label += '  ⭐ Max';
                                if (context.parsed.y === minVal) label += '  🥇 Min';
                                label += `\nNgày: ${day.Ngày}`;
                                return label;
                            }
                        }
                    }
                },
                maintainAspectRatio: false,
                responsive: true
            }
        });

        return this.dailyChart;
    }

    // Highlight cột lớn nhất/nhỏ nhất bằng hiệu ứng glow
    highlightBarGlow(chart, color = '#e961ab') {
        if (!chart) return;

        const ctx = chart.ctx;
        const dataset = chart.data.datasets[0];
        if (!dataset) return;

        const max = Math.max(...dataset.data);
        const min = Math.min(...dataset.data);

        chart.getDatasetMeta(0).data.forEach((bar, i) => {
            if (dataset.data[i] === max || dataset.data[i] === min) {
                ctx.save();
                ctx.shadowColor = color;
                ctx.shadowBlur = 18;
                ctx.globalAlpha = 0.7;
                ctx.beginPath();
                ctx.arc(bar.x, bar.y, 18, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
                ctx.restore();
            }
        });
    }

    // Update charts khi đổi theme
    updateChartsTheme() {
        const currentTheme = document.body.getAttribute('data-theme') || 'dark-gradient';
        const themeConfig = this.getThemeChartConfig(currentTheme);

        // Update monthly chart if exists
        if (this.monthlyChart) {
            this.monthlyChart.options.plugins.legend.labels.color = themeConfig.textColor;
            this.monthlyChart.options.scales.x.ticks.color = themeConfig.textColor;
            this.monthlyChart.options.scales.y.ticks.color = themeConfig.textColor;
            this.monthlyChart.options.scales.x.grid.color = themeConfig.gridColor;
            this.monthlyChart.options.scales.y.grid.color = themeConfig.gridColor;
            this.monthlyChart.update('none');
        }

        // Update daily chart if exists
        if (this.dailyChart) {
            this.dailyChart.options.plugins.legend.labels.color = themeConfig.textColor;
            this.dailyChart.options.scales.x.ticks.color = themeConfig.textColor;
            this.dailyChart.options.scales.y.ticks.color = themeConfig.textColor;
            this.dailyChart.options.scales.x.grid.color = themeConfig.gridColor;
            this.dailyChart.options.scales.y.grid.color = themeConfig.gridColor;
            this.dailyChart.update('none');
        }
    }

    // Get theme-specific chart configuration
    getThemeChartConfig(themeName) {
        const configs = {
            'dark-gradient': { textColor: '#e0e0e0', gridColor: 'rgba(224, 224, 224, 0.1)' },
            'cyberpunk': { textColor: '#00ff9f', gridColor: 'rgba(0, 255, 159, 0.2)' },
            'neon-dreams': { textColor: '#ffffff', gridColor: 'rgba(255, 20, 147, 0.2)' },
            'aurora-borealis': { textColor: '#ffffff', gridColor: 'rgba(26, 140, 255, 0.2)' },
            'synthwave': { textColor: '#ff00ff', gridColor: 'rgba(255, 0, 255, 0.2)' },
            'glassmorphism': { textColor: '#333333', gridColor: 'rgba(51, 51, 51, 0.1)' },
            'neubrutalism': { textColor: '#000000', gridColor: 'rgba(0, 0, 0, 0.3)' },
            'matrix-rain': { textColor: '#00ff00', gridColor: 'rgba(0, 255, 0, 0.2)' },
            'sunset-vibes': { textColor: '#ffffff', gridColor: 'rgba(255, 255, 255, 0.2)' },
            'ocean-depth': { textColor: '#87ceeb', gridColor: 'rgba(135, 206, 235, 0.2)' },
            'midnight-purple': { textColor: '#dda0dd', gridColor: 'rgba(221, 160, 221, 0.2)' },
            'golden-hour': { textColor: '#8b4513', gridColor: 'rgba(139, 69, 19, 0.2)' },
            'forest-mist': { textColor: '#f0fff0', gridColor: 'rgba(240, 255, 240, 0.2)' },
            'cosmic-dust': { textColor: '#e6e6fa', gridColor: 'rgba(230, 230, 250, 0.2)' },
            'tokyo-night': { textColor: '#a9b1d6', gridColor: 'rgba(169, 177, 214, 0.2)' },
            'minimal-light': { textColor: '#333333', gridColor: 'rgba(51, 51, 51, 0.1)' }
        };

        return configs[themeName] || configs['dark-gradient'];
    }

    // Get current theme colors
    getCurrentThemeColors() {
        const currentTheme = document.body.getAttribute('data-theme') || 'dark-gradient';
        return this.getThemeChartConfig(currentTheme);
    }
}

// Export cho sử dụng global
window.ChartManager = ChartManager;
