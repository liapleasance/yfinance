function Foo(a){if(!(this instanceof Foo))return new Foo(a);this.a=a}
Foo.prototype.get=function(){return this.a};
export const inst=Foo(1);
export const v=inst.get();
export const msg="hello from lib - sentinel string";
