FROM public.ecr.aws/lambda/python:3.13

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gmail_auth.py agent.py lambda_function.py ./

CMD ["lambda_function.handler"]
