# Braelo Chatbot (RAG + business matching)

This app powers the chatbot: answers from your **knowledge base** (DOCX Q&A) and **business search** by location.

## Knowledge base (required for Q&A answers)

The bot answers questions from a loaded knowledge base. If you see generic “clarify / share your location” instead of real answers, **load your DOCX data**:

1. **Put your DOCX files** in one of these (you can store them **outside** braelo/chatbot):
   - **Recommended:** In braelo `.env` set `DOCX_DATA_DIR` to your folder, e.g. `DOCX_DATA_DIR=D:\path\to\your\documents`
   - Or use folders **outside braelo:** `braelo_backend/documents/`, `braelo_backend/data/`, `braelo_backend/chatbot_documents/`
   - Or inside: `braelo/chatbot/data/`, `braelo/data/`, `braelo/`

2. **Expected files:**
   - `Lista de Perguntas - IA.docx` (optional; list of questions)
   - `Respostas <State>.docx` (e.g. `Respostas Arizona.docx`, `Respostas Texas.docx`)
   - `Palavras chaves.docx` (optional; for keywords region)

3. **Load into Django DB (default):**
   ```bash
   cd braelo
   python manage.py load_docx
   ```
   Use `--translate` to store answers in English; use `--dry-run` to preview.

4. **If you use MongoDB for knowledge** (`USE_MONGO=true`):
   ```bash
   python manage.py load_mongo_data
   ```

5. **OpenAI:** Set `OPENAI_API_KEY` in `.env` so the app can compute embeddings and run RAG. Without it, semantic search will not work.

After loading, **restart the server** and ask again; the bot will answer from the knowledge base even if the user has not yet shared state/county/ZIP (location is only required for **business search**).
