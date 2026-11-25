# DBMS Unit 3: Normalization

## Why normalization
Normalization is the process of organising the columns and tables of a relational database to reduce data redundancy and avoid update, insert and delete anomalies. A badly designed table that stores student details and course details together repeats the same data many times.

## Functional dependency
A functional dependency X -> Y means that the value of attribute set X uniquely determines the value of Y. For example, roll_no -> student_name holds because one roll number belongs to exactly one student. Functional dependencies are the basis for deciding normal forms.

## First normal form (1NF)
A relation is in first normal form when every attribute holds only atomic values and there are no repeating groups. A column that stores "DBMS, OS, CN" as one value violates 1NF and must be split into separate rows.

## Second normal form (2NF)
A relation is in second normal form when it is in 1NF and every non-prime attribute is fully functionally dependent on the whole candidate key. Partial dependency, where a non-key attribute depends on only part of a composite key, violates 2NF.

## Third normal form (3NF)
A relation is in third normal form when it is in 2NF and no non-prime attribute is transitively dependent on a candidate key. If roll_no -> dept_id and dept_id -> dept_name, then dept_name is transitively dependent on roll_no and should move to a separate department table.

## Boyce-Codd normal form (BCNF)
BCNF is a stronger version of 3NF. A relation is in BCNF when, for every non-trivial functional dependency X -> Y, X is a super key. Every BCNF relation is in 3NF, but not every 3NF relation is in BCNF.

## Exam tips
Questions usually ask you to find the candidate keys from a set of functional dependencies, identify the highest normal form and decompose the relation into 3NF or BCNF. Always check that the decomposition is lossless and, for 3NF, dependency preserving.
