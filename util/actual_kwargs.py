# https://stackoverflow.com/questions/1408818/getting-the-the-keyword-arguments-actually-passed-to-a-python-method
def actual_kwargs():
    """
    Decorator that provides the wrapped function with an attribute 'actual_kwargs'
    containing just those keyword arguments actually passed in to the function.
    """
    def decorator(function):

        print("fuction", function)

        def inner(*args, **kwargs):
            inner.actual_kwargs = kwargs

            print("kwargs", kwargs)
            print("args", args)
            print("actual_kwargs", actual_kwargs)
            print("inner.actual_kwargs", inner.actual_kwargs)

            return function(*args, **kwargs)        
        return inner    
    return decorator
