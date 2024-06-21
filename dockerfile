FROM python:3.11


WORKDIR /app

COPY ./requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

COPY . /app

ENV PYTHONUNBUFFERED=0

CMD ["python","-u","main.py"]
