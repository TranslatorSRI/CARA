import time

import pytest
from testcontainers.compose import DockerCompose


@pytest.fixture(scope="session")
def session(request):
    print("starting docker container")

    compose = DockerCompose(filepath=".", compose_file_name="docker-compose.yml", env_file=".env", build=False, pull=True)
    compose.start()
    nn_service_name = compose.get_service_host(service_name="cara", port=8080)
    nn_service_port = compose.get_service_port(service_name="cara", port=8080)
    nn_url = f"http://{nn_service_name}:{nn_service_port}"
    print(f"nn_url: {nn_url}")
    compose.wait_for(f"{nn_url}")

    # seems we need to wait for rabbitmq to start up
    time.sleep(3)

    print(f"done building docker containers...ready to proceed")

    def stop():
        print("stopping docker container")
        stdout, stderr = compose.get_logs()
        if stderr:
            print(f"{str(stderr, 'utf-8')}")
        if stdout:
            print(f"{str(stdout, 'utf-8')}")
        compose.stop()

    request.addfinalizer(stop)

    return compose
