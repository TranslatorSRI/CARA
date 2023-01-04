# leverage the renci python base image
FROM renciorg/renci-python-image:v0.0.1

RUN mkdir /code
WORKDIR /code

# install library
COPY ./requirements.txt requirements.txt
COPY ./src src

# install requirements
RUN pip install -r requirements.txt

RUN chmod 777 ./

USER nru
ENTRYPOINT ["uvicorn", "--host", "0.0.0.0", "--port", "8080", "--workers", "5", "src.server:APP"]
