#!/bin/bash
# Quick start script for local development

set -e

echo "🚀 Starting Olivia development environment..."
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not found. Please install Docker Compose."
    exit 1
fi

echo "✅ Docker is installed"
echo ""

# Check if Ollama is running
echo "⏳ Checking Ollama..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama is running"
else
    echo "⚠️  Ollama not found on localhost:11434"
    echo "   Please start Ollama separately:"
    echo "   $ ollama serve"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "🐳 Starting Docker services..."
docker-compose up --build

echo ""
echo "✅ Services started!"
echo ""
echo "Frontend: http://localhost:5173"
echo "Backend:  http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
echo ""
