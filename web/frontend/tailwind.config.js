/** @type {import('tailwindcss').Config} */
// 配色参考微信读书本身（figma 抽取）：冷灰底 + 石板色字 + 微信蓝强调
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#F4F5F7',        // 页面底色，微信读书冷灰
        surface: '#FFFFFF',
        line: '#E6E9EE',         // 冷灰描边
        ink: {
          DEFAULT: '#212832',    // 正文（深石板）
          soft: '#5D646E',       // 次要文字
          faint: '#99A0AA',      // 辅助/时间
        },
        // 沿用 clay 这个 token 名，值改为微信读书蓝（避免大面积改类名）
        clay: {
          DEFAULT: '#1B88EE',    // 微信读书蓝
          ink: '#1670C9',
          soft: '#EAF4FE',       // 蓝色浅底
          tint: 'rgba(27,136,238,0.06)',  // 图标底片（weread 官网风格）
        },
      },
      backgroundImage: {
        // weread 官网标志性渐变 CTA
        'clay-grad': 'linear-gradient(90deg, #0087FC 0%, #28B7FF 100%)',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'PingFang SC',
               'Hiragino Sans GB', 'Microsoft YaHei', 'sans-serif'],
        serif: ['Georgia', 'Noto Serif SC', 'Songti SC', 'STSong', 'serif'],
      },
      boxShadow: {
        card: '0px 4px 60px rgba(0, 0, 0, 0.04)',  // 微信读书卡片的极柔阴影
        airy: '0px 0px 80px rgba(0, 0, 0, 0.04)',  // weread 官网大半径柔光
      },
    },
  },
  plugins: [],
}
