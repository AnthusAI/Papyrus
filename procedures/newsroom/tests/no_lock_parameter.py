"""An SSM client double for tests that patch boto3.client: the projection lock table parameter does not exist."""


class NoLockParameter:
    def get_parameter(self, Name):
        error = Exception(f"ParameterNotFound: {Name}")
        error.response = {"Error": {"Code": "ParameterNotFound"}}
        raise error
