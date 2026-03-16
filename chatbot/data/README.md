# Chatbot knowledge base – DOCX files

**Put your Q&A DOCX files in this folder**, then run:

```bash
# From braelo folder (with venv activated):
python manage.py load_mongo_data    # if you use MongoDB (USE_MONGO=true)
# or
python manage.py load_docx          # if you use Django DB for knowledge
```

## Expected files

- **Respostas &lt;State&gt;.docx** – e.g. `Respostas Arizona.docx`, `Respostas Texas.docx`, `Respostas NY.docx`
- **Lista de Perguntas - IA.docx** – (optional) list of questions
- **Palavras chaves.docx** – (optional) keywords region

After adding the files here, run the command above again to load them into the knowledge base.
