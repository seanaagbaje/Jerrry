/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        "primary": "#136dec",
        "background-light": "#f6f7f8",
        "background-dark": "#101822",
      },
      fontFamily: { "display": ["Lexend", "sans-serif"] },
    },
  },
  plugins: [],
}

