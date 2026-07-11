#!/bin/bash
echo "Waiting for Qdrant..."
until curl -s http://qdrant:6333/collections > /dev/null; do
  sleep 2
done
echo "Qdrant is up. Launching Streamlit..."
exec streamlit run ui/app.py --server.port=8501 --server.address=0.0.0.0