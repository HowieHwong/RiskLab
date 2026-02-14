#!/usr/bin/env bash
# =============================================================================
# build_docs.sh — RiskLab documentation build script
#
# Usage:
#   ./docs/build_docs.sh              # Build HTML documentation
#   ./docs/build_docs.sh clean        # Clean build artifacts
#   ./docs/build_docs.sh install      # Install Sphinx dependencies and build
#   ./docs/build_docs.sh serve        # Build and start local preview server
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCS_DIR="$SCRIPT_DIR"
BUILD_DIR="$DOCS_DIR/_build"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check if Sphinx is installed
check_sphinx() {
    if ! command -v sphinx-build &> /dev/null; then
        warn "sphinx-build not found."
        echo "Please run: pip install sphinx sphinx_rtd_theme"
        echo "Or use: $0 install"
        exit 1
    fi
}

# Install dependencies
do_install() {
    info "Installing Sphinx and dependencies..."
    pip install sphinx sphinx_rtd_theme
    info "Installing RiskLab (editable mode)..."
    pip install -e "$PROJECT_ROOT"
    info "Dependencies installed successfully."
}

# Clean
do_clean() {
    info "Cleaning build directory: $BUILD_DIR"
    rm -rf "$BUILD_DIR"
    info "Clean complete."
}

# Build HTML
do_build() {
    check_sphinx
    info "Building HTML documentation..."
    cd "$DOCS_DIR"
    sphinx-build -b html . "$BUILD_DIR/html" -W --keep-going 2>&1 || {
        warn "Warnings encountered during build. Rebuilding without -W flag..."
        sphinx-build -b html . "$BUILD_DIR/html"
    }
    echo ""
    info "Documentation build complete!"
    info "Output directory: $BUILD_DIR/html"
    info "Open in browser: xdg-open $BUILD_DIR/html/index.html"
}

# Start local preview server
do_serve() {
    do_build
    info "Starting local preview server..."
    cd "$BUILD_DIR/html"
    python -m http.server 8000 &
    SERVER_PID=$!
    info "Documentation preview: http://localhost:8000"
    info "Press Ctrl+C to stop the server"
    trap "kill $SERVER_PID 2>/dev/null; exit 0" INT TERM
    wait $SERVER_PID
}

# Main entry point
case "${1:-build}" in
    install)
        do_install
        do_build
        ;;
    clean)
        do_clean
        ;;
    serve)
        do_serve
        ;;
    build|html)
        do_build
        ;;
    help|--help|-h)
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  build     Build HTML documentation (default)"
        echo "  clean     Clean build artifacts"
        echo "  install   Install dependencies and build"
        echo "  serve     Build and start local preview server"
        echo "  help      Show this help message"
        ;;
    *)
        error "Unknown command: $1. Run '$0 help' for usage information."
        ;;
esac
